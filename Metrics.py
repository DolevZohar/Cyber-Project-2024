class Metrics:
    url
    load_time
    memory_usage
    cpu_time

    def __init__(self, url, load_time, memory_usage, cpu_time):
        self.url = url
        self.load_time = load_time
        self.memory_usage = memory_usage
        self.cpu_time = cpu_time
