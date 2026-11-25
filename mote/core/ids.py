"""会话与节点的标识符。

只依赖时间与随机数，不读写文件；日志里出现过的 ID 由调用方负责落盘。
"""

import datetime
import random


DEFAULT_SESSION = "main"


def new_session_id():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"s-{stamp}-{random.randrange(0x1000, 0xFFFF):04x}"


def new_node_id():
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return f"n-{stamp}-{random.randrange(0x1000, 0xFFFF):04x}"
