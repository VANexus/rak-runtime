import sys
import os
from flask import Flask, render_template, request, jsonify
import logging

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 把项目根目录加入检索路径
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../'))
from src.core.decision_engine import DecisionEngine

app = Flask(__name__)
engine = DecisionEngine()

# 动作常量定义
AVAILABLE_ACTIONS = [
    "shake_head", "wave_hand", "lock_open", "lock_close",
    "move_forward", "move_back", "turn_left", "turn_right",
    "nod", "dance", "emergency_stop"
]

ACTION_NAMES = {
    "shake_head": "摇头", "wave_hand": "挥手", "lock_open": "开门", "lock_close": "关门",
    "move_forward": "前进", "move_back": "后退", "turn_left": "左转", "turn_right": "右转",
    "nod": "点头", "dance": "跳舞", "emergency_stop": "停止"
}

# 前端首页路由
@app.route('/')
def index():
    return render_template('index.html')

# 对话接口
@app.route('/api/chat', methods=['POST'])
def chat():
    text = request.json.get('text', '').strip()
    if not text:
        return jsonify({"reply": "请输入指令"}), 400

    logger.info(f"用户输入指令：{text}")
    actions = engine._rule_decompose(text, AVAILABLE_ACTIONS)
    logger.info(f"动作分解结果：{actions}")

    if actions:
        name_list = [ACTION_NAMES.get(item["action"], item["action"]) for item in actions]
        reply = f"好的，将执行：{'、'.join(name_list)}"
    else:
        reply = "抱歉未能识别指令，可尝试：开门、挥手、前进然后左转"

    return jsonify({"reply": reply, "actions": actions})

if __name__ == '__main__':
    logger.info("聊天服务启动成功，访问地址：http://localhost:5000")
    app.run(debug=True, port=5000)