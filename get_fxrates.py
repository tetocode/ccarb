from pprint import pprint
import re

import lxml.html
import requests


def get_fxrates():
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


pprint(get_fxrates())
