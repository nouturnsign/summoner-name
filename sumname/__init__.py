import asyncio as _asyncio
import itertools as _itertools
import json as _json
import queue as _queue
import random as _random
import threading as _threading
from io import TextIOWrapper as _TextIOWrapper
from typing import Union as _Union

import bs4 as _bs4
import cloudscraper as _cloudscraper
import keras as _keras
import numpy as _np
import requests as _requests
from tqdm import tqdm as _tqdm

class UnrandomSummoner:

  scraper = _cloudscraper.create_scraper()
  BUILD_ID = _json.loads(
        _bs4.BeautifulSoup(scraper.get("https://op.gg/"
        ).content, "html.parser").find(
            "script", {"id": "__NEXT_DATA__", "type": "application/json"}).get_text()
            )["buildId"]
  WAIT = 60
  SAFE_THRESHOLD_FACTOR = 1.1

  def __init__(self, region: str, summoner: str):

    self.region = region
    self.summoner = summoner
    self._generator = self.generate_from(self.region, self.summoner)

  def generate_next(self, n: int):

    for _ in range(n):
      yield next(self._generator)

  def generate_to_file_next(self, path: _Union[str, _TextIOWrapper], n: int, verbose: bool=True):

    generator = _itertools.islice(self._generator, n)
    if verbose:
      generator = _tqdm(generator, total=n)

    if isinstance(path, str):
      path = open(path, 'w')

    with path as f:
      for summoner in generator:
        f.write(summoner + '\n')

  @classmethod
  async def safely_wait_for_data(cls, region: str, summoner: str):

    url = f"https://{region}.op.gg/_next/data/{cls.BUILD_ID}/summoners/{region}/{summoner}.json?region={region}&summoner={summoner}"
    resp = cls.scraper.get(url)

    while resp.status_code != 200:
      await _asyncio.sleep(cls.WAIT)
      url = f"https://{region}.op.gg/_next/data/{cls.BUILD_ID}/summoners/{region}/{summoner}.json?region={region}&summoner={summoner}"
      resp = cls.scraper.get(url)
    
    return resp.json()

  @classmethod
  async def _add_participants_head(cls, region: str, summoner: str, remaining: _Union[_queue.Queue, _queue.LifoQueue]):
    
    data = await cls.safely_wait_for_data(region, summoner)

    matches = data['pageProps']['games']
    participants = (set() if len(matches) == 0 
                    else set(
                        participant['summoner']['name'] 
                        for match in matches['data'] 
                        if match is not None
                        for participant in match['participants']
                        if participant['summoner'] is not None
                        )
                    )
    
    for participant in participants:
      remaining.put(participant)

  @classmethod
  def _loop_in_thread(cls, loop: str, region: str, summoner: str, remaining: _Union[_queue.Queue, _queue.LifoQueue]):

    _asyncio.set_event_loop(loop)
    loop.run_until_complete(cls._add_participants_head(region, summoner, remaining))

  @classmethod
  def generate_from(cls, region: str, summoner: str, maximum: int=None):

    if maximum is None:
      maximum = float("inf")

    remaining = _queue.LifoQueue()
    remaining.put(summoner)
    seen = set()

    while len(seen) < maximum:
      summoner = remaining.get()
      while summoner in seen:
        summoner = remaining.get()
      seen.add(summoner)
      yield summoner
      if remaining.qsize() < cls.SAFE_THRESHOLD_FACTOR * maximum:
        t = _threading.Thread(target=cls._loop_in_thread, args=(_asyncio.new_event_loop(), region, summoner, remaining))
        t.start()

  @classmethod
  def generate_to_file_from(cls, path: _Union[str, _TextIOWrapper], region: str, summoner: str, maximum: int, verbose: bool=True):

    generator = cls.generate_from(region, summoner, maximum)
    if verbose:
      generator = _tqdm(generator, total=maximum)

    if isinstance(path, str):
      path = open(path, 'w')

    with path as f:
      for summoner in generator:
        f.write(summoner + '\n')
        
class FakeSummoner:
  
  def __init__(self):

    path = 'https://github.com/nouturnsign/summoner-name/raw/master/models'
    name = 'lowelo_1e4_model'
    
    self.M = 13
    self.TEXT = _requests.get(f"{path}/{name}.txt").content.decode('utf-8').replace('\n', '\n ')
    self.CHARS = sorted(set(TEXT))
    self.CHAR_INDICES = {}
    for i, char in enumerate(CHARS):
      self.CHAR_INDICES[char] = i

    weights_path = _keras.utils.data_utils.get_file(name, f"{path}/{name}.h5")
    self.model = _keras.models.Sequential()
    self.model.add(_keras.layers.LSTM(128, input_shape=(M, len(CHARS))))
    self.model.add(_keras.layers.Dense(len(CHARS), activation='softmax'))
    self.model.load_weights(weights_path)
    self.model.compile(loss='categorical_crossentropy', optimizer='rmsprop')

  @staticmethod
  def sample(preds: _np.ndarray, temperature: float=1.0):

    preds = _np.asarray(preds).astype('float64')
    preds = _np.log(preds) / temperature
    exp_preds = _np.exp(preds)
    preds = exp_preds / _np.sum(exp_preds)
    probas = _np.random.multinomial(1, preds, 1)
    return _np.argmax(probas)

  def generate_next(self, n: int):

    start_index = _random.randint(0, len(self.TEXT) - self.M - 1)
    generated_text = self.TEXT[start_index: start_index + self.M]

    for i in range(n):
      sampled = _np.zeros((1, self.M, len(self.CHARS)))
      for t, char in enumerate(generated_text):
          sampled[0, t, self.CHAR_INDICES[char]] = 1.

      preds = self.model.predict(sampled, verbose=0)[0]
      next_index = self.sample(preds)
      next_char = self.CHARS[next_index]

      generated_text += next_char
      yield next_char.replace('\n', '')
      generated_text = generated_text[1:]
