# PersonaPlex 服务端部署指南

## 环境要求
- NVIDIA GPU（显存≥16GB，推荐24GB）
- Python 3.10+
- CUDA 11.8+
- uv 包管理器（项目统一依赖管理工具）

## 部署步骤
1. 克隆仓库
```bash
git clone https://github.com/NVIDIA/personaplex.git
cd personaplex
```

2. 创建虚拟环境并安装依赖
```bash
uv venv --python 3.10
source .venv/bin/activate
uv pip install moshi/.
```

3. 登录 Hugging Face（需要先接受模型许可）
```bash
huggingface-cli login
```

4. 启动服务（后台运行）
```bash
nohup python -m moshi.server --host 0.0.0.0 --port 8998 &
```

## 验证部署
服务启动后，访问 **http://服务器IP:8998** 可以看到 Web 界面，或者运行客户端代码测试连接。

## 客户端配置
客户端默认连接地址：ws://8.129.26.180:8998/ws
如需修改，在**realtime_personaplex.py**中调整 PERSONAPLEX_SERVER 变量即可。