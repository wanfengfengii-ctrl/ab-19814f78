# Toolpath Audit Service

精密探针程序在下发到运动控制器之前的审计服务。它逐行执行探针程序，确认整条轨迹
（而不仅是终点）留在闭合工作空间内，并且不接触任何夹具禁入区（包括边界），全部
换算与相交裁决均保持十进制精确。

纯 Python 3 标准库实现（`decimal.Decimal` 精确十进制运算），无第三方依赖。

## API

### `GET /health`

健康检查，返回 `{"status": "ok"}`。

### `POST /api/toolpaths/audit`

请求体（坐标可用 JSON 数字或十进制字符串，一律按精确十进制解析）：

```json
{
  "initial_position": {"x": "0", "y": "0", "z": "0"},
  "workspace": {
    "min": {"x": "-100", "y": "-100", "z": "-100"},
    "max": {"x": "100", "y": "100", "z": "100"}
  },
  "forbidden_zones": [
    {"min": {"x": "10", "y": "-1", "z": "-1"}, "max": {"x": "20", "y": "1", "z": "1"}}
  ],
  "program": "G21\nG90\nG1 X50\n"
}
```

* `initial_position`：初始坐标（毫米），必须位于工作空间闭区间内。
* `workspace`：闭合轴对齐长方体工作空间（毫米）。
* `forbidden_zones`：至多 20 个闭合轴对齐长方体禁入区（毫米），可省略。
* `program`：至多 5000 行的程序文本。

**成功**（HTTP 200）：返回规范化为毫米的线段与最终坐标。

```json
{
  "ok": true,
  "units": "mm",
  "segment_count": 1,
  "segments": [{"start": {"x": "0", "y": "0", "z": "0"}, "end": {"x": "50", "y": "0", "z": "0"}}],
  "final_position": {"x": "50", "y": "0", "z": "0"}
}
```

**审计失败**（HTTP 200，`ok: false`，绝不携带任何可下发的部分轨迹）：

```json
{
  "ok": false,
  "error": {
    "line": 3,
    "reason": "forbidden_zone_violation",
    "message": "line 3: segment touches forbidden zone 0",
    "zone_index": 0
  }
}
```

`line` 为原始程序的 1 起始行号（与行无关的失败为 `null`）；`zone_index` 为禁入区在
请求数组中的 0 起始编号（非禁入区失败为 `null`）。处理逐行顺序进行，稳定报告首个
违规行；同一线段触及多个禁入区时报告最小编号。

**请求非法**（HTTP 400）：字段缺失、类型错误、禁入区超过 20 个、程序超过 5000 行、
`min > max`、非规范十进制等，`reason` 为 `invalid_request`。

### 失败原因（`error.reason`）

| reason | 含义 |
| --- | --- |
| `illegal_word` | 非法词：不支持的字母/G 代码、畸形词、非规范十进制（如指数形式） |
| `duplicate_axis` | 同一行出现重复轴词 |
| `conflicting_modal` | 同一行出现同组冲突模态（G0/G1、G20/G21、G90/G91） |
| `non_finite_decimal` | 非有限十进制（NaN / Infinity） |
| `missing_motion_mode` | 尚未建立运动模式（G0/G1）便给出坐标 |
| `workspace_violation` | 线段端点越出闭合工作空间 |
| `forbidden_zone_violation` | 线段与禁入区内部或边界接触 |
| `invalid_request` | 请求结构非法（HTTP 400） |

## 程序语言

* 行导向；`;` 起注释至行尾；空行与纯注释行不产生运动。
* 词 = 字母 + 紧随的规范十进制数（`[+-]?(数字[.数字]|.数字)`；不接受指数、NaN、Infinity）。
* `G0`/`G1` 直线运动（模态）；`G20`/`G21` 英寸/毫米（模态）；`G90`/`G91` 绝对/相对坐标（模态）。
* 轴词 `X` `Y` `Z`。每个含轴词的运动行产生一条线段（含零长线段）。
* 模态设置跨行持续生效；**同一行上的新设置先作用于该行坐标**（如 `G20 G91 G1 X1`
  中的 `X1` 按英寸、相对解释）。
* 默认 G21（毫米）、G90（绝对）；运动模式初始未建立，此时给出坐标即报错。
* 初始位置与每个线段端点都必须位于工作空间闭区间内；线段与任一禁入区的内部
  **或边界**接触即拒绝。

## 精确性

* 全程使用 `decimal.Decimal`；英寸换算系数 25.4 为精确值。
* 相交判定为无除法的 slab 法：各轴的参数区间以分数保存，交叉相乘比较，
  因此 `0.1 + 0.2` 恰好等于 `0.3`，边界接触判定无浮点误差。

## 运行

```bash
docker compose up api                 # 默认宿主机端口 8000
AUDIT_PORT=9000 docker compose up api # 宿主机端口可配置
```

本地无 Docker 时：`python3 -m app.main`（环境变量 `PORT` 改端口，默认 8000）。

## 验证

`verify` 为一次性服务：等待 API 健康后依次执行代码测试（unittest）、构建
（字节编译全部源码）和 API 冒烟（含英寸相对移动用例），以退出码报告结果：

```bash
docker compose up --abort-on-container-exit --exit-code-from verify
echo $?   # 0 = 全部通过
```

本地等价命令：

```bash
python3 -m unittest discover -s tests -t . -v   # 代码测试
python3 -m compileall -q app scripts tests      # 构建（字节编译）
python3 -m app.main &                            # 启动 API
API_BASE_URL=http://127.0.0.1:8000 python3 scripts/smoke.py
```

## 布局

```
app/
  geometry.py    精确线段-长方体相交判定（无除法）
  gcode.py       程序解析与解释、工作空间/禁入区裁决
  validation.py  请求体验证（JSON 数字直接解析为 Decimal）
  server.py      HTTP API（标准库 http.server）
  main.py        入口：python -m app.main
scripts/smoke.py 冒烟测试（含英寸相对移动）
tests/           unittest 测试套件
Dockerfile       服务镜像（无 pip 安装步骤）
docker-compose.yml  api（健康检查、可配置宿主机端口）+ verify（一次性验证）
```
