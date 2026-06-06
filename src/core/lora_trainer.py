"""
LoRA 微调训练器 — 程序性知识沉淀。

将执行日志和程序性记忆转化为训练数据，
通过 LoRA 微调本地小模型（如 Qwen2-0.5B）实现：
  - 快速动作分类（<10ms，替代 LLM API 调用）
  - 离线场景下的决策能力
  - 个性化行为学习

训练流程：
  1. 从记忆引擎收集程序性记忆（成功/失败模式）
  2. 转化为指令微调格式 (instruction, input, output)
  3. LoRA 微调本地模型
  4. 导出适配器权重供推理使用

依赖：
  pip install transformers peft datasets torch

注意：首次运行需要下载基础模型（~1GB）。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ── 训练数据格式 ──

@dataclass
class TrainingSample:
    """一条训练样本。"""
    instruction: str       # 系统指令
    input: str            # 用户输入（状态/动作描述）
    output: str           # 期望输出（JSON 格式的动作决策）
    source: str = "memory"  # 数据来源：memory / log / manual

@dataclass
class TrainingConfig:
    """LoRA 微调配置。"""
    # 基础模型
    base_model: str = "Qwen/Qwen2-0.5B"

    # LoRA 参数
    lora_r: int = 8           # LoRA 秩
    lora_alpha: int = 16      # LoRA 缩放因子
    lora_dropout: float = 0.05
    lora_target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj"])

    # 训练参数
    num_epochs: int = 3
    batch_size: int = 4
    learning_rate: float = 2e-4
    warmup_steps: int = 50
    max_seq_length: int = 512

    # 输出
    output_dir: str = "models/lora_action_classifier"

    # 可用动作列表
    available_actions: List[str] = field(default_factory=lambda: [
        "lock_open", "lock_close", "move_forward", "move_back",
        "wave_hand", "shake_head", "nod", "dance",
        "light_on", "light_off", "emergency_stop",
    ])


# ── 数据收集器 ──

class DataCollector:
    """从记忆引擎和执行日志收集训练数据。"""

    SYSTEM_PROMPT = """你是一个嵌入式设备动作分类器。根据用户的状态描述或指令，选择最合适的动作并输出 JSON。

可用动作: {actions}

输出格式: {{"action": "动作名", "priority": 0|1|2, "params": {{}}}}
priority: 0=实时控制, 1=交互动作, 2=管理查询"""

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.samples: List[TrainingSample] = []

    def collect_from_memory(self, memory_engine=None) -> int:
        """从记忆引擎收集程序性记忆作为训练数据。"""
        if memory_engine is None:
            logger.warning("记忆引擎不可用，跳过记忆收集")
            return 0

        count = 0
        try:
            # 检索程序性记忆
            results = memory_engine.search(
                memory_type="procedural",
                top_k=100,
            )

            for result in results:
                entry = result.entry
                # 解析记忆内容，提取动作模式
                sample = self._parse_procedural_memory(entry)
                if sample:
                    self.samples.append(sample)
                    count += 1

            # 检索情景记忆中的成功案例
            results = memory_engine.search(
                memory_type="episodic",
                top_k=100,
            )

            for result in results:
                entry = result.entry
                if "成功" in entry.content or "ok" in entry.content.lower():
                    sample = self._parse_episodic_memory(entry)
                    if sample:
                        self.samples.append(sample)
                        count += 1

            logger.info(f"从记忆引擎收集 {count} 条训练样本")
        except Exception as e:
            logger.error(f"记忆收集失败: {e}")

        return count

    def collect_from_log_file(self, log_path: str) -> int:
        """从执行日志文件收集训练数据。"""
        if not os.path.exists(log_path):
            logger.warning(f"日志文件不存在: {log_path}")
            return 0

        count = 0
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        sample = self._parse_log_entry(entry)
                        if sample:
                            self.samples.append(sample)
                            count += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"日志读取失败: {e}")

        logger.info(f"从日志文件收集 {count} 条训练样本")
        return count

    def add_manual_sample(self, instruction: str, input_text: str, output_action: str):
        """手动添加训练样本。"""
        self.samples.append(TrainingSample(
            instruction=self.SYSTEM_PROMPT.format(actions=", ".join(self.config.available_actions)),
            input=input_text,
            output=output_action,
            source="manual",
        ))

    def _parse_procedural_memory(self, entry) -> Optional[TrainingSample]:
        """解析程序性记忆为训练样本。"""
        content = entry.content
        # 尝试提取动作模式
        # 格式: "执行 lock_open 时需要先检查门锁状态"
        for action in self.config.available_actions:
            if action in content:
                return TrainingSample(
                    instruction=self.SYSTEM_PROMPT.format(actions=", ".join(self.config.available_actions)),
                    input=f"何时应该执行 {action}？",
                    output=json.dumps({"action": action, "priority": 1, "params": {}}),
                    source="memory",
                )
        return None

    def _parse_episodic_memory(self, entry) -> Optional[TrainingSample]:
        """解析情景记忆为训练样本。"""
        content = entry.content
        # 格式: "语音指令: '开门' → 动作: lock_open (LLM决策)"
        if "→" in content:
            parts = content.split("→")
            if len(parts) >= 2:
                input_text = parts[0].strip()
                action_part = parts[1].strip()
                for action in self.config.available_actions:
                    if action in action_part:
                        return TrainingSample(
                            instruction=self.SYSTEM_PROMPT.format(actions=", ".join(self.config.available_actions)),
                            input=input_text,
                            output=json.dumps({"action": action, "priority": 1, "params": {}}),
                            source="memory",
                        )
        return None

    def _parse_log_entry(self, entry: dict) -> Optional[TrainingSample]:
        """解析日志条目为训练样本。"""
        # 日志格式: {"input": "...", "action": "...", "status": "ok", ...}
        action = entry.get("action", "")
        input_text = entry.get("input", "") or entry.get("state", "")
        status = entry.get("status", "")

        if not action or not input_text:
            return None

        if action not in self.config.available_actions:
            return None

        # 只收集成功案例
        if status not in ("ok", "executed", "queued"):
            return None

        priority = entry.get("priority", 1)

        return TrainingSample(
            instruction=self.SYSTEM_PROMPT.format(actions=", ".join(self.config.available_actions)),
            input=input_text,
            output=json.dumps({"action": action, "priority": priority, "params": {}}),
            source="log",
        )

    def export_jsonl(self, output_path: str) -> int:
        """导出训练数据为 JSONL 格式。"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            for sample in self.samples:
                record = {
                    "instruction": sample.instruction,
                    "input": sample.input,
                    "output": sample.output,
                    "source": sample.source,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info(f"导出 {len(self.samples)} 条训练数据到 {output_path}")
        return len(self.samples)


# ── LoRA 训练器 ──

class LoRATrainer:
    """LoRA 微调训练器。"""

    def __init__(self, config: TrainingConfig):
        self.config = config

    def train(self, data_path: str) -> str:
        """
        执行 LoRA 微调训练。

        Args:
            data_path: JSONL 训练数据路径

        Returns:
            输出目录路径
        """
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
            from peft import LoraConfig, get_peft_model, TaskType
            from datasets import load_dataset
            from trl import SFTTrainer
        except ImportError as e:
            raise ImportError(
                f"缺少训练依赖: {e}\n"
                "请安装: pip install transformers peft datasets torch trl"
            )

        logger.info(f"开始 LoRA 微调: base_model={self.config.base_model}")

        # 加载基础模型
        tokenizer = AutoTokenizer.from_pretrained(
            self.config.base_model,
            trust_remote_code=True,
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None,
            trust_remote_code=True,
        )

        # 配置 LoRA
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=self.config.lora_r,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.lora_target_modules,
            bias="none",
        )

        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()

        # 加载数据集
        dataset = load_dataset("json", data_files=data_path, split="train")

        def format_sample(sample):
            """格式化训练样本为模型输入。"""
            if sample.get("input"):
                text = f"### 指令:\n{sample['instruction']}\n\n### 输入:\n{sample['input']}\n\n### 回答:\n{sample['output']}"
            else:
                text = f"### 指令:\n{sample['instruction']}\n\n### 回答:\n{sample['output']}"
            return {"text": text}

        dataset = dataset.map(format_sample)

        # 训练参数
        output_dir = os.path.join(os.getcwd(), self.config.output_dir)
        training_args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=self.config.num_epochs,
            per_device_train_batch_size=self.config.batch_size,
            learning_rate=self.config.learning_rate,
            warmup_steps=self.config.warmup_steps,
            logging_steps=10,
            save_strategy="epoch",
            fp16=torch.cuda.is_available(),
            report_to="none",
        )

        # 开始训练
        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=dataset,
            dataset_text_field="text",
            max_seq_length=self.config.max_seq_length,
            tokenizer=tokenizer,
        )

        logger.info("训练开始...")
        trainer.train()

        # 保存 LoRA 适配器
        adapter_dir = os.path.join(output_dir, "adapter")
        model.save_pretrained(adapter_dir)
        tokenizer.save_pretrained(adapter_dir)

        logger.info(f"LoRA 适配器已保存到: {adapter_dir}")
        return adapter_dir


# ── 推理器 ──

class LoRAInference:
    """LoRA 模型推理器（用于快速动作分类）。"""

    def __init__(self, adapter_path: str, base_model: str = None):
        self.adapter_path = adapter_path
        self.base_model = base_model
        self.model = None
        self.tokenizer = None

    def load(self):
        """加载模型和适配器。"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel
            import torch
        except ImportError as e:
            raise ImportError(f"缺少推理依赖: {e}")

        # 从适配器配置读取基础模型
        if self.base_model is None:
            adapter_config_path = os.path.join(self.adapter_path, "adapter_config.json")
            if os.path.exists(adapter_config_path):
                with open(adapter_config_path) as f:
                    config = json.load(f)
                    self.base_model = config.get("base_model_name_or_path", "Qwen/Qwen2-0.5B")

        logger.info(f"加载基础模型: {self.base_model}")
        base = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None,
            trust_remote_code=True,
        )

        logger.info(f"加载 LoRA 适配器: {self.adapter_path}")
        self.model = PeftModel.from_pretrained(base, self.adapter_path)
        self.tokenizer = AutoTokenizer.from_pretrained(self.adapter_path, trust_remote_code=True)

        logger.info("LoRA 推理模型加载完成")

    def classify(self, input_text: str, available_actions: List[str]) -> Optional[dict]:
        """
        快速动作分类（<10ms on GPU）。

        Returns:
            {"action": "...", "priority": 0|1|2, "params": {}} 或 None
        """
        if self.model is None:
            self.load()

        import torch

        system = f"你是一个嵌入式设备动作分类器。可用动作: {', '.join(available_actions)}"
        prompt = f"### 指令:\n{system}\n\n### 输入:\n{input_text}\n\n### 回答:\n"

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=128,
                temperature=0.1,
                do_sample=False,
            )

        response = self.tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

        # 解析 JSON 输出
        try:
            # 提取 JSON
            if "{" in response:
                json_str = response[response.index("{"):response.rindex("}") + 1]
                result = json.loads(json_str)
                if result.get("action") in available_actions:
                    return result
        except (json.JSONDecodeError, ValueError):
            pass

        return None


# ── 便捷函数 ──

def create_training_data(memory_engine=None, log_path: str = None, output_path: str = "data/training.jsonl") -> int:
    """创建训练数据的便捷函数。"""
    config = TrainingConfig()
    collector = DataCollector(config)

    if memory_engine:
        collector.collect_from_memory(memory_engine)

    if log_path:
        collector.collect_from_log_file(log_path)

    # 添加基础训练样本（确保最小数据集）
    _add_base_samples(collector, config)

    return collector.export_jsonl(output_path)


def _add_base_samples(collector: DataCollector, config: TrainingConfig):
    """添加基础训练样本（关键词→动作映射）。"""
    base_mappings = [
        ("开门", "lock_open", 0),
        ("关门", "lock_close", 0),
        ("前进", "move_forward", 0),
        ("后退", "move_back", 0),
        ("挥手", "wave_hand", 1),
        ("摇头", "shake_head", 1),
        ("点头", "nod", 1),
        ("跳舞", "dance", 1),
        ("停止", "emergency_stop", 0),
        ("开灯", "light_on", 1),
        ("关灯", "light_off", 1),
    ]

    for text, action, priority in base_mappings:
        if action in config.available_actions:
            collector.add_manual_sample(
                instruction=config.SYSTEM_PROMPT.format(actions=", ".join(config.available_actions)),
                input_text=text,
                output_action=json.dumps({"action": action, "priority": priority, "params": {}}, ensure_ascii=False),
            )
