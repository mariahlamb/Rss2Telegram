from bs4 import BeautifulSoup
from telebot import types
from time import gmtime
import feedparser
import os
import re
import telebot
import telegraph
import time
import random
import requests
import sqlite3

def get_variable(variable):
    return os.getenv(variable) or open(f'{variable}.txt', 'r').read()

URL = get_variable('URL')
DESTINATION = get_variable('DESTINATION')
BOT_TOKEN = get_variable('BOT_TOKEN')
EMOJIS = os.getenv('EMOJIS', '🗞,📰,🗒,🗓,📋,🔗,📝,🗃')
PARAMETERS = os.getenv('PARAMETERS', '')
HIDE_BUTTON = os.getenv('HIDE_BUTTON', 'False') == 'True'
DRYRUN = os.getenv('DRYRUN', '')
TOPIC = os.getenv('TOPIC', False)
TELEGRAPH_TOKEN = os.getenv('TELEGRAPH_TOKEN', '')

bot = telebot.TeleBot(BOT_TOKEN)

def add_to_history(link):
    with sqlite3.connect('rss2telegram.db') as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO history (link) VALUES (?)', (link,))
        conn.commit()

def check_history(link):
    with sqlite3.connect('rss2telegram.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM history WHERE link = ?', (link,))
        return cursor.fetchone()

def firewall(text):
    try:
        with open('RULES.txt', 'r') as rules:
            for rule in rules:
                opt, arg = map(str.strip, rule.split(':'))
                if (arg == 'ALL' and opt == 'DROP'):
                    return False
                if (arg == 'ALL' and opt == 'ACCEPT'):
                    return True
                if (arg.lower() in text.lower() and opt == 'DROP'):
                    return False
                if (arg.lower() in text.lower() and opt == 'ACCEPT'):
                    return True
            return True
    except FileNotFoundError:
        return True

def create_telegraph_post(topic):
    telegraph_auth = telegraph.Telegraph(access_token=TELEGRAPH_TOKEN)
    response = telegraph_auth.create_page(
        title=topic["title"],
        html_content=(
            f'{topic["summary"]}<br><br>'
            f'<a href="{topic["link"]}">Ver original ({topic["site_name"]})</a>'
        ),
        author_name=topic["site_name"]
    )
    return response["url"]

def send_message(topic, button):
    if DRYRUN == 'failure':
        return

    MESSAGE_TEMPLATE = os.getenv('MESSAGE_TEMPLATE', '<b>{TITLE}</b>').replace('\n', ' ')
    MESSAGE_TEMPLATE = set_text_vars(MESSAGE_TEMPLATE, topic)

    if TELEGRAPH_TOKEN:
        iv_link = create_telegraph_post(topic)
        MESSAGE_TEMPLATE = f'<a href="{iv_link}"></a>{MESSAGE_TEMPLATE}'

    if not firewall(str(topic)):
        print(f'Blocked: {topic["title"]}')
        return

    btn_link = types.InlineKeyboardMarkup() if button else None
    if button:
        btn = types.InlineKeyboardButton(text=button, url=topic['link'])
        btn_link.row(btn)

    recipients = DESTINATION.split(',')
    for dest in recipients:
        try:
            if topic['photo'] and not TELEGRAPH_TOKEN:
                with requests.get(topic['photo'], headers={'User-agent': 'Mozilla/5.1'}, stream=True) as response:
                    if response.status_code == 200:
                        with open('img', 'wb') as img_file:
                            for chunk in response.iter_content(1024):
                                img_file.write(chunk)
                        with open('img', 'rb') as photo:
                            bot.send_photo(dest, photo, caption=MESSAGE_TEMPLATE, parse_mode='HTML', reply_markup=btn_link, reply_to_message_id=TOPIC)
            else:
                bot.send_message(dest, MESSAGE_TEMPLATE, parse_mode='HTML', reply_markup=btn_link, disable_web_page_preview=True, reply_to_message_id=TOPIC)
            print(f'Message sent: {topic["title"]}')
            time.sleep(0.2)
        except telebot.apihelper.ApiTelegramException as e:
            print(f'Error sending message: {e}')
            if topic['photo']:
                topic['photo'] = False
                send_message(topic, button)  # try again without the photo

def get_img(url):
    try:
        response = requests.get(url, headers={'User-agent': 'Mozilla/5.1'}, timeout=3)
        html = BeautifulSoup(response.content, 'html.parser')
        return html.find('meta', {'property': 'og:image'})['content']
    except (TypeError, requests.exceptions.RequestException):
        return False

def define_link(link):
    return f'{link}?{PARAMETERS}' if PARAMETERS and '?' not in link else link

def set_text_vars(text, topic):
    cases = {
        'SITE_NAME': topic['site_name'],
        'TITLE': topic['title'],
        'SUMMARY': re.sub('<[^<]+?>', '', topic['summary']),
        'LINK': define_link(topic['link']),
        'EMOJI': random.choice(EMOJIS.split(","))
    }
    for key, value in cases.items():
        text = text.replace(f'{{{key}}}', value)
    return text

def check_topics(url):
    feed = feedparser.parse(url)
    if 'feed' not in feed:
        print(f'ERRO: {url} não parece um feed RSS válido.')
        return
    source = feed['feed']['title']
    print(f'\nChecando {source}: {url}')
    for tpc in reversed(feed.get('items', [])[:10]):
        link = tpc.links[0].href
        if check_history(link):
            continue
        add_to_history(link)
        topic = {
            'site_name': source,
            'title': tpc.title.strip(),
            'summary': tpc.summary,
            'link': link,
            'photo': get_img(link)
        }
        BUTTON_TEXT = os.getenv('BUTTON_TEXT', '').strip()
        send_message(topic, BUTTON_TEXT)

if __name__ == "__main__":
    for url in URL.split():
        check_topics(url)
