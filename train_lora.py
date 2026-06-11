#!/usr/bin/env python3
"""
LoRA 微调训练脚本 — 程序性知识沉淀。

用法:
  # 1. 生成训练数据（从记忆引擎 + 日志）
  python train_lora.py collect --log data/execution_log.jsonl

  # 2. 训练 LoRA 适配器
  python train_lora.py train --data data/training.jsonl

  # 3. 测试推理
  python train_lora.py test --input "开门"

  # 4. 完整流程（收集 + 训练）
  python train_lora.py all --log data/execution_log.jsonl
"""
import argparse
import logging
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("train_lora")


def cmd_collect(args):
    """收集训练数据。"""
    from src.core.lora_trainer import TrainingConfig, DataCollector, _add_base_samples

    config = TrainingConfig()
    collector = DataCollector(config)

    # 从记忆引擎收集
    if not args.skip_memory:
        try:
            from src.core.memory_engine import CognitiveMemoryEngine
            memory = CognitiveMemoryEngine()
            count = collector.collect_from_memory(memory)
            logger.info(f"从记忆引擎收集 {count} 条")
        except Exception as e:
            logger.warning(f"记忆引擎不可用: {e}")

    # 从日志文件收集
    if args.log:
        count = collector.collect_from_log_file(args.log)
        logger.info(f"从日志文件收集 {count} 条")

    # 添加基础样本
    _add_base_samples(collector, config)

    # 导出
    output = args.output or "data/training.jsonl"
    total = collector.export_jsonl(output)
    logger.info(f"训练数据已生成: {output} ({total} 条)")


def cmd_train(args):
    """执行 LoRA 微调。"""
    from src.core.lora_trainer import TrainingConfig, LoRATrainer

    config = TrainingConfig()

    if args.base_model:
        config.base_model = args.base_model
    if args.epochs:
        config.num_epochs = args.epochs
    if args.lr:
        config.learning_rate = args.lr
    if args.output_dir:
        config.output_dir = args.output_dir

    data_path = args.data or "data/training.jsonl"
    if not os.path.exists(data_path):
        logger.error(f"训练数据不存在: {data_path}")
        logger.info("请先运行: python train_lora.py collect")
        return

    trainer = LoRATrainer(config)
    adapter_path = trainer.train(data_path)
    logger.info(f"训练完成! 适配器路径: {adapter_path}")


def cmd_test(args):
    """测试 LoRA 推理。"""
    from src.core.lora_trainer import LoRAInference, TrainingConfig

    config = TrainingConfig()
    adapter_path = args.adapter or os.path.join(config.output_dir, "adapter")

    if not os.path.exists(adapter_path):
        logger.error(f"适配器不存在: {adapter_path}")
        logger.info("请先运行: python train_lora.py train")
        return

    inference = LoRAInference(adapter_path, config.base_model)
    inference.load()

    test_inputs = args.input or "开门"
    logger.info(f"测试输入: {test_inputs}")

    result = inference.classify(test_inputs, config.available_actions)
    if result:
        logger.info(f"分类结果: {result}")
    else:
        logger.warning("分类失败，无法解析输出")


def cmd_all(args):
    """完整流程：收集 + 训练。"""
    logger.info("=== 步骤 1: 收集训练数据 ===")
    cmd_collect(args)

    logger.info("=== 步骤 2: 训练 LoRA ===")
    cmd_train(args)

    logger.info("=== 完成! ===")


def main():
    parser = argparse.ArgumentParser(description="LoRA 微调训练工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # collect
    p_collect = subparsers.add_parser("collect", help="收集训练数据")
    p_collect.add_argument("--log", help="执行日志文件路径")
    p_collect.add_argument("--output", "-o", help="输出文件路径")
    p_collect.add_argument("--skip-memory", action="store_true", help="跳过记忆引擎收集")

    # train
    p_train = subparsers.add_parser("train", help="执行 LoRA 微调")
    p_train.add_argument("--data", "-d", help="训练数据路径")
    p_train.add_argument("--base-model", help="基础模型名称")
    p_train.add_argument("--epochs", type=int, help="训练轮次")
    p_train.add_argument("--lr", type=float, help="学习率")
    p_train.add_argument("--output-dir", "-o", help="输出目录")

    # test
    p_test = subparsers.add_parser("test", help="测试推理")
    p_test.add_argument("--input", "-i", help="测试输入文本")
    p_test.add_argument("--adapter", "-a", help="适配器路径")

    # all
    p_all = subparsers.add_parser("all", help="完整流程")
    p_all.add_argument("--log", help="执行日志文件路径")
    p_all.add_argument("--output", "-o", help="输出文件路径")
    p_all.add_argument("--skip-memory", action="store_true", help="跳过记忆引擎收集")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "collect": cmd_collect,
        "train": cmd_train,
        "test": cmd_test,
        "all": cmd_all,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
