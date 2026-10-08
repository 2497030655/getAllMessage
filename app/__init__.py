"""消息聚合应用包。"""

__all__ = ["create_app"]


def __getattr__(name: str):
    if name == "create_app":
        from app.factory import create_app

        return create_app
    raise AttributeError(name)
