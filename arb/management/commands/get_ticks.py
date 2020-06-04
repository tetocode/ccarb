from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import itertools
import logging
import pickle
from pprint import pprint
import re
import threading
import time
from typing import Dict, Tuple

import ccxt
from django.core.management.base import BaseCommand
from django.db import transaction
from docopt import docopt
import lxml.html
import oandapy
import requests

from ...models import LastTick


class Command(BaseCommand):
    fx_rates = {}
    quotes = []
    bases = []
    interval = 30
    brokers = {}  # type: Dict[Tuple[str, str], ccxt.Exchange]
    brokers_instruments = {}  # type: Dict[str, Dict[str, dict]]
    fx_fiats = ['JPY', 'USD', 'EUR']
    TOKEN = "<TOKEN>"
    ACCOUNT_ID = "<ACCOUNT_ID>"
    oanda = oandapy.API(access_token=TOKEN)
    pool = ThreadPoolExecutor(max_workers=50)

    def run_from_argv(self, argv):
        args = docopt("""
        Usage:
          {f} [options]

        Options:
          --quotes QUOTES  [default: JPY,USD,EUR,IDR,PHP,AUD,HKD,SGD,BTC,ETH,QSH,QASH]
          --bases BASES  [default: BTC,ETH,BCH,QSH,QASH]
          --interval SEC  [default: 25]
          --brokers BROKERS  [default: bitfinex,bitmex,bitflyer,coincheck,quoine,zaif]
          
        """.format(f=argv[1]), argv[2:])

        print('#arguments')
        pprint(args)
        self.quotes = list(map(lambda x: x.upper(), args['--quotes'].split(',')))
        self.bases = list(map(lambda x: x.upper(), args['--bases'].split(',')))
        self.interval = float(args['--interval'])
        self.broker_names = args['--brokers'].split(',')
        self.start()

    def start(self):
        self.quoine = ccxt.quoine()
        brokers = []
        for name in self.broker_names:
            brokers.append(getattr(ccxt, name)())
        #        if 'bitflyer' in self.
        #            ccxt.bitflyer(),
        #            ccxt.coincheck(),
        #            ccxt.zaif(),
        #            ccxt.quoine(),
        # ccxt.kraken(),
        #            ccxt.bitmex(),
        #            ccxt.bitfinex(),
        #        ]
        brokers = {x.id: x for x in brokers}
        for x in self.brokers.values():
            x.timeout = 5000
        self.brokers = self.reload_markets(brokers)

        # self.update_fx_rates()

        threading.Thread(target=self.update_fx_rates_loop, daemon=True).start()
        i = 0
        while True:
            try:
                self.action(i)
            except Exception as e:
                logging.exception(str(e))
            i += 1
            time.sleep(self.interval)

    def action(self, i):
        if i % 100 == 0:
            pass  # self.reload_markets()
        print('#', datetime.utcnow())
        fx_rates = self.fx_rates
        all_ticks = self.get_ticks()
        now = datetime.utcnow()

        for tick in all_ticks:
            if fx_rates.get(tick['quote'] + '/JPY'):
                ask = tick['ask'] * fx_rates[tick['quote'] + '/JPY']['ask']
            else:
                ask = None
            if fx_rates.get(tick['quote'] + '/JPY'):
                bid = tick['bid'] * fx_rates[tick['quote'] + '/JPY']['bid']
            else:
                bid = None
            tick['ask_jpy'] = ask
            tick['bid_jpy'] = bid

        # pairs = self.calc_pairs(all_ticks)
        # cycles = self.calc_cycles(all_ticks)

        with transaction.atomic():
            last_tick, _ = LastTick.objects.get_or_create(id=LastTick.UUID)
            last_tick.data = pickle.dumps({
                'fx': fx_rates,
                'crypto': all_ticks,
            })
            last_tick.save()

    def calc_pairs(self, all_ticks):
        results = []
        for a, b in itertools.permutations(all_ticks, 2):
            if a['base'] != b['base']:
                continue
            pair = {
                'rate': b['bid_jpy'] / a['ask_jpy'],
                'diff': b['bid_jpy'] - a['ask_jpy'],
                'a': a, 'b': b, 'c': None, 'd': None,
            }
            results.append(pair)
        results.sort(key=lambda x: -x['diff'])
        return results

    def calc_cycles(self, all_ticks):
        results = []
        for a, b, c, d in itertools.permutations(all_ticks, 4):
            if len({a['name'], b['name'], c['name'], d['name']}) != 1:
                continue
            if a['quote'] != d['quote'] or a['base'] != b['base'] or b['quote'] != c['quote'] or c['base'] != d[
                'base']:
                continue
            rate = d['bid_jpy'] / a['ask_jpy'] * b['bid_jpy'] / c['ask_jpy']
            results.append({
                'rate': rate,
                'diff': 500000 * (rate - 1),
                'a': a, 'b': b, 'c': c, 'd': d,
            })
        results.sort(key=lambda x: -x['diff'])
        return results

    def reload_markets(self, brokers):
        def reload(broker):
            try:
                print('#reload {}'.format(broker.id))
                broker.load_markets(reload=True)
            except Exception as e:
                logging.exception('reload exception {} {}'.format(broker.id, str(e)))

        list(self.pool.map(reload, brokers.values()))

        instruments = {}
        instrument_brokers = {}
        for name, broker in brokers.items():
            markets = broker.load_markets()
            for instrument, data in markets.items():
                base, quote = data['base'], data['quote']
                if base not in self.bases or quote not in self.quotes:
                    continue
                if name == 'bitmex' and '.' in instrument:
                    continue
                if name == 'coincheck' and instrument != 'BTC/JPY':
                    continue
                if name == 'kraken' and '/' not in instrument:
                    continue
                instruments.setdefault(name, {})[instrument] = data
                instrument_brokers[(name, instrument)] = type(broker)()
        list(self.pool.map(reload, instrument_brokers.values()))
        self.brokers_instruments = instruments
        print('#', instrument_brokers)
        return instrument_brokers

    def update_fx_rates_loop(self):
        while True:
            try:
                self.update_fx_rates2()
            except Exception as e:
                logging.exception(str(e))
            time.sleep(60)

    def update_fx_rates2(self):
        fx_rates = self.get_fxrates()
        fx_rates = {
            k: {
                'instrument': k,
                'ask': v,
                'bid': v,
                'mid': v,
                'base': k[:3],
                'quote': k[-3:],
                'name': 'yahoo',
                'is_fiat': True,
            } for k, v in fx_rates.items()}
        for quote in self.quotes:
            instrument = '{}/JPY'.format(quote)
            if instrument not in self.quoine.loadMarkets():
                continue
            book = self.quoine.fetchOrderBook(instrument)
            mid = (book['asks'][0][0] + book['bids'][0][0]) / 2
            ask = book['asks'][0][0]
            bid = book['bids'][0][0]
            fx_rates[instrument] = {
                'instrument': instrument,
                'ask': ask,
                'bid': bid,
                'mid': mid,
                'base': instrument[:3],
                'quote': instrument[-3:],
                'name': 'coin',
                'is_fiat': True,
            }
        for x in sorted(fx_rates.values(), key=lambda x: x['instrument']):
            print(x['instrument'], x['ask'], x['bid'])

        self.fx_rates = fx_rates

    def update_fx_rates(self):
        instruments = ['{}_JPY'.format(x) for x in self.fx_fiats if x != 'JPY']
        prices = self.oanda.get_prices(instruments=','.join(instruments))['prices']
        fx_rates = [{
            'instrument': x['instrument'].replace('_', '/'),
            'ask': x['ask'],
            'bid': x['bid'],
            'mid': (x['ask'] + x['bid']) / 2,
            'base': x['instrument'][:3],
            'quote': x['instrument'][-3:],
        } for x in prices]
        fx_rates.append({
            'instrument': 'JPY/JPY',
            'ask': 1,
            'bid': 1,
            'mid': 1,
            'base': 'JPY',
            'quote': 'JPY',
        })
        results = {}
        for a, b in itertools.permutations(fx_rates, 2):
            instrument = '{}/{}'.format(a['base'], b['base'])
            results[instrument] = {
                'name': 'oanda',
                'instrument': instrument,
                'is_fiat': True,
                'ask': a['ask'] / b['bid'],
                'bid': a['bid'] / b['ask'],
                'mid': (a['ask'] / b['bid'] + a['bid'] / b['ask']) / 2,
                'base': a['base'],
                'quote': b['base'],
            }
        results['JPY/JPY'] = {
            'name': '',
            'instrument': 'JPY/JPY',
            'is_fiat': True,
            'ask': 1,
            'bid': 1,
            'mid': 1,
            'base': 'JPY',
            'quote': 'JPY',
        }
        self.fx_rates = results

    def get_fxrates(self):
        URL = 'https://info.finance.yahoo.co.jp/fx/convert/'
        res = requests.get(URL)
        root = lxml.html.fromstring(res.text)
        doms = root.cssselect('.fxRateTbl.fxList')
        usd = doms[0].text_content()
        jpy = doms[1].text_content()

        names = {
            'アメリカ　ドル.*': 'USD',
            '欧州　ユーロ.*': 'EUR',
            # 'ブラジル　レアル.*' : '',
            'オーストラリア　ドル.*': 'AUD',
            '中国　元.*': 'CNY',
            # 'イギリス　ポンド.*' : '',
            # '韓国　ウォン.*' : '',
            # 'ニュージーランド　ドル.*' : '',
            'シンガポール　ドル.*': 'SGD',
            # 'タイ　バーツ.*' : '',
            # '台湾　ドル.*' : '',
            # '南アフリカ　ランド.*' : '',
            # 'カナダ　ドル.*' : '',
            # 'トルコ　リラ.*' : '',
            '香港　ドル.*': 'HKD',
            # 'スイス　フラン.*' : '',
            # 'マレーシア　リンギット.*' : '',
            # 'メキシコ　ペソ.*' : '',
            'フィリピン　ペソ.*': 'PHP',
            'インド　ルピー.*': 'INR',
            'インドネシア　ルピア.*': 'IDR',
            # 'ロシア　ルーブル.*' : '',
            # 'スウェーデン　クローナ.*' : '',
            # 'ノルウェー　クローネ.*' : '',
            # 'デンマーク　クローネ.*' : '',
            # 'UAE　ディルハム.*' : '',
            # 'チリ　ペソ.*' : '',
            # 'ベネズエラ　ボリバル・フエルテ.*' : '',
            # 'クウェート　ディナール.*' : '',
            # 'サウジアラビア　リヤル.*' : '',
            # 'ルーマニア　レウ.*' : '',
            # 'パラグアイ　グァラニ.*' : '',
            # 'エジプト　ポンド.*' : '',
            # 'コロンビア　ペソ.*' : '',
            # 'ヨルダン　ディナール.*' : '',
            # 'ペルー　ソル.*' : '',
            # 'レバノン　ポンド.*' : '',
        }
        rates = {
            'JPY/JPY': 1.0
        }
        for m in re.finditer('(?P<name>[^\d]+?)(?P<rate>[\d.]+)', jpy):
            d = m.groupdict()
            for k, v in names.items():
                if re.search(k, d['name']):
                    rates['{}/JPY'.format(v)] = float(d['rate'])
                    break
        if not (100 <= rates.get('USD/JPY', 0) < 125):
            for k in rates:
                rates[k] = 0
        return rates

    def get_ticks(self):
        arg_list = []
        for _name, _instruments in self.brokers_instruments.items():
            for _instrument in _instruments:
                arg_list.append((_name, _instrument))

        def get_order_book(arg):
            name, instrument = arg
            broker = self.brokers[(name, instrument)]
            try:
                params = {}
                if broker.id == 'quoine':
                    params.update(full=1)
                book = broker.fetchOrderBook(instrument, params=params)
                book['name'] = broker.id
                base = self.brokers_instruments[name][instrument]['base']
                quote = self.brokers_instruments[name][instrument]['quote']
                instrument = instrument.replace('QSH', 'QASH')
                base = base.replace('QSH', 'QASH')
                quote = quote.replace('QSH', 'QASH')
                book['instrument'] = instrument
                book['base'] = base
                book['quote'] = quote
                if base == 'BTC':
                    threshold = 1.5
                elif base == 'ETH':
                    threshold = 20
                elif base == 'QASH':
                    threshold = 500  # 880000 * 1.5 / 37
                else:
                    threshold = 1
                # assert False, (name, instrument, base)
                if not book['asks'] or not book['bids']:
                    logging.warning('no data %s', arg)
                    return None
                if name == 'bitmex':
                    if instrument == 'BTC/USD':
                        threshold *= (book['asks'][0][0] + book['bids'][0][0]) / 2
                    elif instrument.startswith('XBT'):
                        threshold *= (book['asks'][0][0] + book['bids'][0][0]) / 2
                    elif instrument.startswith('XBJ'):
                        threshold *= (book['asks'][0][0] + book['bids'][0][0]) / 2 / 100
                book['qty_threshold'] = threshold
                book['best_ask'] = book['asks'][0][0]
                book['best_ask_qty'] = book['asks'][0][1]
                book['best_bid'] = book['bids'][0][0]
                book['best_bid_qty'] = book['bids'][0][1]
                for k in ['ask', 'bid']:
                    book[k] = None
                    book[k + '_qty'] = None
                    qty = 0.0
                    for x in book[k + 's']:
                        qty += x[1]
                        if qty >= threshold:
                            book[k] = x[0]
                            book[k + '_qty'] = qty
                            break
                    else:
                        logging.warning('no data %s', arg)
                        return None
                    del book[k + 's']
                return book
            except Exception as e:
                logging.exception('%s:%s get_tick failed : %s', name, instrument, str(e))
                return None

        return list(filter(bool, self.pool.map(get_order_book, arg_list)))
