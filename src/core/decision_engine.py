# src/core/decision_engine.py
import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class DecisionEngine:
    def __init__(self):
        # 可以在这里加载配置或初始化
        pass

    def decide(self, request) -> dict:
        """
        核心决策逻辑，对应参考案例中的分析流程。
        返回: 一个包含 decision, params, error 的字典。
        """
        trace_id = request.trace_id
        logger.info(f"[TraceID: {trace_id}] 决策引擎启动...")

        # === 步骤 1: 输入校验 (对应参考案例的规则引擎) ===
        validation_result = self._validate_request(request)
        if not validation_result["is_valid"]:
            return {
                "status": "error",
                "error_code": "INVALID_REQUEST",
                "error_message": validation_result["message"]
            }

        # === 步骤 2: 决策模式判断 ===
        if request.action:
            # 模式1: 动作确认
            decision = self._handle_action_confirmation(request)
        else:
            # 模式2: 状态转动作
            decision = self._handle_state_to_action(request)
            
        logger.info(f"[TraceID: {trace_id}] 决策完成: {decision.get('action')}")
        return decision

    def _validate_request(self, request) -> dict:
        """请求校验逻辑"""
        # 校验 available_actions 是否存在
        if not request.available_actions:
            return {"is_valid": False, "message": "available_actions 不能为空"}
        
        # 校验 action 是否在白名单内 (如果指定了 action)
        if request.action and request.action not in request.available_actions:
            return {
                "is_valid": False, 
                "message": f"动作 '{request.action}' 不在允许列表 {request.available_actions} 中"
            }
        
        # 校验 params_json 是否为合法 JSON
        if request.params_json:
            try:
                json.loads(request.params_json)
            except json.JSONDecodeError:
                return {"is_valid": False, "message": "params_json 不是有效的 JSON 格式"}
        
        return {"is_valid": True}

    def _handle_action_confirmation(self, request) -> dict:
        """处理前端指定的动作"""
        # 这里可以添加更复杂的业务逻辑，比如参数动态修改等
        return {
            "status": "ok",
            "action": request.action,
            "params_json": request.params_json
        }

    def _handle_state_to_action(self, request) -> dict:
        """处理由 Runtime 自动决策的场景"""
        if not request.available_actions:
            return {"status": "error", "error_code": "NO_AVAILABLE_ACTIONS", "error_message": "无可用动作"}

        # 最简单的决策：选第一个
        chosen_action = request.available_actions[0]
        
        # 为不同动作设置默认参数
        default_params = {}
        if chosen_action == "move_forward":
            default_params = {"distance_cm": 5, "speed": 50}
        elif chosen_action == "turn_left":
            default_params = {"angle_deg": 90, "speed": 30}
        # ... 可以继续添加其他动作的默认参数

        return {
            "status": "ok",
            "action": chosen_action,
            "params_json": json.dumps(default_params, ensure_ascii=False)
        }