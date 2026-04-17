import queue
import time
MAX_RETRIES = 3

class LocalPubSub:
    def __init__(self):
        self._topics = {}
        self.retries = {}

    def _get_or_create_topic(self, topic_name: str) -> queue.Queue:
        if topic_name not in self._topics:
            self._topics[topic_name] = queue.Queue()
        return self._topics[topic_name]

    def publish(self, topic_name: str, message: dict):
        q = self._get_or_create_topic(topic_name)
        q.put(message)

    def pull(self, topic_name: str, timeout: int = 2) -> dict:
        q = self._get_or_create_topic(topic_name)
        try:
            message = q.get(timeout=timeout)
            return message
        except queue.Empty:
            return None

    def acknowledge(self, topic_name: str): # sucsses
        q = self._get_or_create_topic(topic_name)
        q.task_done()
        
    def nack(self, topic_name: str, message: dict, key: str, is_system_error: bool):
        if is_system_error:
            self.publish(topic_name, message)
        else:
            if key in self.retries:
                self.retries[key] += 1
            else:
                self.retries[key] = 1

            if self.retries[key] >= MAX_RETRIES:
                dlq_topic_name = f'dlq-{topic_name}'
                self.publish(dlq_topic_name,message)
            else:
                self.publish(topic_name, message)