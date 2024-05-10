import asyncio
import random
import string
import argparse
import time
import numpy as np
import curses
from threading import Thread
from threading import Lock

class Message:
    def __init__(self, message: str=None, recipient: str=None):
        # generate some random message if none was provided
        if message is None:
            self.message = ''.join(random.choices(string.ascii_letters, k=random.randint(1, 100)))
        else:
            self.message = message
        
        # generate a random phone number if none was provided
        if recipient is None:
            self.recipient = ''.join(random.choices(string.digits, k=10))
        else:
            self.recipient = recipient

class Producer:
    def __init__(self, num_senders=1000):
        self.__num_senders = num_senders

    def produce(self) -> list[Message]:
        return [Message() for _ in range(self.__num_senders)]

class Sender:

    def __init__(self, mean_delay: float, failure_rate: float, messages: list[Message]):
        std_deviation = 1
        # derived from properties of gamma distribution: shape * scale = mean, and mean*scale = std_deviation
        self.__shape = (mean_delay ** 2) / std_deviation
        self.__scale = std_deviation / mean_delay

        self.__failure_rate = failure_rate
        self.__messages = messages
        self.__messages_sent_lock = Lock()
        self.__num_messages_sent = 0
        self.__messages_failed_lock = Lock()
        self.__num_messages_failed = 0
        self.__elapsed_time_lock = Lock()
        self.__elapsed_time = 0.0
        self.__elapsed_time_denominator = 0

        self.is_sending = False


    async def send_all(self):
        self.is_sending = True
        while len(self.__messages) > 0:
            start = time.perf_counter()
            sent = await self.send(self.__messages[-1])
            elapsed = time.perf_counter() - start
            if sent:
                with self.__elapsed_time_lock:
                    self.__elapsed_time += elapsed
                    self.__elapsed_time_denominator += 1
                self.__messages = self.__messages[:-1]
        self.is_sending = False

    async def send(self, message: Message) -> bool:
        delay = np.random.gamma(self.__shape, self.__scale)
        await asyncio.sleep(delay)

        if random.random() < self.__failure_rate:
            with self.__messages_failed_lock:
                self.__num_messages_failed += 1
            return False
        with self.__messages_sent_lock:
            self.__num_messages_sent += 1
        return True
    
    def get_and_reset_stats(self):
        with self.__messages_failed_lock and self.__messages_sent_lock and self.__elapsed_time_lock:
            messages_failed, elapsed_time, elapsed_time_denominator, messages_sent = self.__num_messages_failed, self.__elapsed_time, self.__elapsed_time_denominator, self.__num_messages_sent
            self.__num_messages_failed, self.__elapsed_time, self.__elapsed_time_denominator, self.__num_messages_sent = 0, 0.0, 0, 0
            return messages_failed, elapsed_time, elapsed_time_denominator, messages_sent
    
class Monitor:
    def __init__(self, tracked_senders: list[Sender], update_delay: float, window: curses.window):
        self.__tracked_senders = tracked_senders
        self.__update_delay = update_delay
        self.__window = window
        self.__num_messages_sent = 0
        self.__num_messages_failed = 0
        self.__total_elapsed_time = 0.0
        self.__elapsed_time_denominator = 0

    async def monitor(self):
        last_pass = False
        while (actively_sending := any(sender.is_sending for sender in self.__tracked_senders)) or not last_pass:
            last_pass = not actively_sending
            for sender in self.__tracked_senders:
                messages_failed, elapsed_time, elapsed_time_denominator, messages_sent = sender.get_and_reset_stats()
                self.__num_messages_sent += messages_sent
                self.__num_messages_failed += messages_failed
                self.__total_elapsed_time += elapsed_time
                self.__elapsed_time_denominator += elapsed_time_denominator
            self.__window.clear()
            self.__window.addstr(0,0, f'Messages sent: {self.__num_messages_sent}')
            self.__window.addstr(1,0, f'Messages failed: {self.__num_messages_failed}')
            self.__window.addstr(2,0, f'Average delay: {self.__total_elapsed_time/self.__elapsed_time_denominator if self.__elapsed_time_denominator != 0 else 0 : .3f}s')
            
            self.__window.refresh()
            await asyncio.sleep(self.__update_delay)
        self.__window.addstr(3,0, 'press any key to close the application')
        self.__window.refresh()
        self.__window.getkey()

def main(window, args: argparse.Namespace):
    producer = Producer(args.messages)

    chunked_messages = np.array_split(producer.produce(), args.senders)

    senders = [Sender(args.delay, args.failure_rate, messages) for messages in chunked_messages]

    threads: list[Thread] = []

    for sender in senders:
        thread = Thread(target=asyncio.run, args=(sender.send_all(),))
        threads.append(thread)
        thread.start()
    
    monitor = Monitor(senders, args.update_delay, window)
    asyncio.run(monitor.monitor())
    for thread in threads:
        thread.join()

def positive_float(arg):
    try:
        f = float(arg)
    except ValueError:
        raise argparse.ArgumentTypeError('must be a floating point number')
    if f < 0:
        raise argparse.ArgumentTypeError('must be a positive float')
    return f

def float_range_inclusive_min_not_inclusive_max(min, max):
    def float_range_check(arg):
        try:
            f = float(arg)
        except ValueError:
            raise argparse.ArgumentTypeError('must be a floating point number')
        if f < min or f >= max:
            raise argparse.ArgumentTypeError(f'must be a floating point number in the range [{min} ... {max})')
        return f
    return float_range_check

def positive_integer(arg):
    try:
        i = int(arg)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer")
    if i < 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer")
    return i

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='SMSSimulator',
                                     description='Simulates the sending of SMS messages')
    
    parser.add_argument('-m', '--messages', default=1000, type=positive_integer, help='Number of messages to be generated')
    parser.add_argument('-s', '--senders', default=1, type=positive_integer, help='Number of senders to create and simulate sending of messages')
    parser.add_argument('-d', '--delay', default=0.0, type=positive_float, help='Mean delay for the time it takes to send a message')
    parser.add_argument('-f', '--failure-rate', default=0.0, type=float_range_inclusive_min_not_inclusive_max(0., 1.), help='Chance for a given message to fail to send')
    parser.add_argument('-u', '--update-delay', default=1, type=positive_float, help='Number of seconds between progress monitor updates')

    args = parser.parse_args()

    curses.wrapper(main, args)