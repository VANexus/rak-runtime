# Python期末综合实验：智能聊天机器人系统

## 一、实验简介
本作业基于我参与开发的中国高校计算机大赛参赛项目**Rak Runtime 具身智能操作系统**的核心规则引擎开发。所有决策逻辑直接复用原项目生产环境代码，没有任何重复实现。

## 二、技术栈
- Python 3.11
- Flask Web框架
- 面向对象编程
- 关键词匹配与多动作分解算法
- 日志记录与异常处理


## 三、项目结构

```plaintext
rak-runtime/
├── src/
│   └── core/
│       └── decision_engine.py  # 原项目核心规则引擎（团队共同开发）
└── homework/
    ├── web/
    │   ├── app.py              # Flask后端
    │   └── templates/
    │       └── index.html      # 前端界面
    └── README.md               # 本实验报告
```


## 四、运行方法
### 前置条件
1. 已经在原项目根目录执行过 `uv sync` 安装了所有依赖
2. 本作业位于原项目根目录下的 `homework/` 文件夹
3. 项目结构如“三、项目结构”图所示

### 启动命令
1. 激活原项目虚拟环境
```bash
source .venv/bin/activate
```

2. 添加依赖
```bash
uv add flask
```
> 如果用uv run触发了 openai-whisper 的构建问题，请用以下指令安装作业专属依赖（仅需执行一次）
```bash
.venv/bin/python -m pip install flask
```

3. 启动聊天服务
```bash
uv run python homework/web/app.py
```

> 如果用uv run触发了 openai-whisper 的构建问题，直接使用python命令即可正常运行。
```bash
python homework/web/app.py
```

> 运行后如果终端出现如下红色警告：
```plaintext
WARNING: This is a development server. Do not use it in a production deployment.
```
这是 Flask 开发模式的标准提示，完全**正常**。


4. 访问系统
打开浏览器访问：http://127.0.0.1:5000

## 五、功能说明
1. **核心功能**：将自然语言指令分解为多个原子动作
2. **支持指令**：开门、关门、挥手、摇头、前进、后退、左转、右转、点头、跳舞、停止
3. **多动作支持**：支持 "开门然后挥手再点头" 这类复杂指令
> **指令示例：**
> 
> 开门然后挥手再点头
> 
> 前进然后左转再后退
> 
> 关门然后跳舞
> 
> 紧急停止
4. **日志记录**：所有请求和决策结果都会在终端输出

## 六、注意事项
1. 本作业依赖原项目的核心规则引擎，必须在原项目的虚拟环境中运行
2. 不要修改原项目根目录下的 pyproject.toml 文件
3. 作业的所有依赖都已通过 uv 安装，不需要额外配置
4. 所有核心功能均已测试通过，按照上述步骤运行即可正常使用
