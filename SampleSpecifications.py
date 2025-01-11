class SampleSpecification:
    url
    optimal_load_time
    load_time_weight
    optimal_memory_usage
    memory_usage_weight
    optimal_cpu_time
    cpu_time_weight
    browser[4]
    browser_weight[4]
    isDefaultBrowserWeight


    def __init__(self, url, optimal_load_time, load_time_weight, optimal_memory_usage, memory_usage_weight, optimal_cpu_time, cpu_time_weight, browser[4], browser_weight[4], isDefaultBrowserWeight):
        self.url = url
        self.optimal_load_time = optimal_load_time
        self.load_time_weight = load_time_weight
        self.optimal_memory_usage = optimal_memory_usage
        self.memory_usage_weight = memory_usage_weight
        self.optimal_cpu_time = optimal_cpu_time
        self.cpu_time_weight = cpu_time_weight
        self.browser = browser
        self.browser_weight = browser_weight
        self.isDefaultBrowserWeight = isDefaultBrowserWeight