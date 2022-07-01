import asyncio as _asyncio
import itertools as _itertools
import json as _json
import queue as _queue
import threading as _threading
from io import TextIOWrapper as _TextIOWrapper

import bs4 as _bs4
import cloudscraper as _cloudscraper
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

  def generate_to_file_next(self, path: str | _TextIOWrapper, n: int, verbose: bool=True):

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
  async def _add_participants_head(cls, region: str, summoner: str, remaining: _queue.Queue | _queue.LifoQueue):
    
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
  def _loop_in_thread(cls, loop: str, region: str, summoner: str, remaining: _queue.Queue | _queue.LifoQueue):

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
  def generate_to_file_from(cls, path: str | _TextIOWrapper, region: str, summoner: str, maximum: int, verbose: bool=True):

    generator = cls.generate_from(region, summoner, maximum)
    if verbose:
      generator = _tqdm(generator, total=maximum)

    if isinstance(path, str):
      path = open(path, 'w')

    with path as f:
      for summoner in generator:
        f.write(summoner + '\n')