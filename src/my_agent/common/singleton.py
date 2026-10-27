def singleton(cls):
    """单例装饰器：全进程只有一个实例。

    存在的理由：保护"全局只能有一份真相"的状态（路由表、缓存、配置），
    不是限制使用次数。参照 CowAgent common/singleton.py。
    """
    instances = {}

    def wrapper(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return wrapper
