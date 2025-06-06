class Metrics:
    def __init__(self, url, **kwargs):
        self.url = url
        for key, value in kwargs.items():
            if value is None and not isinstance(value, list):
                value = -1
            setattr(self, key, value)

    def to_dict(self):
        return self.__dict__

    @classmethod
    def from_dict(cls, d):
        return cls(**d)
