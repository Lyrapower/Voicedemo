# Paper Trading 铁律(写死在代码,不靠自觉)
1. 账户恒为 paper —— account.mode == "paper",真实下单模块永不 import
2. broker_execution = False 写死,和 Jarvis 同一保险
3. $1000 是模拟额度,但风控按真钱配 —— 否则学不到真避险
4. 每笔决策留痕(进场理由/仓位/风控参数/finish_reason)进 ledger
5. 本实验目标 = 行为审计,不是收益。收益只记录不当 KPI
