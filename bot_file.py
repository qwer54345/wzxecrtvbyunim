#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import time
import asyncio
import sqlite3
import re
import threading
import urllib.request
import random
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Dict, Any, Optional, Tuple, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ==================== إعدادات السجل ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ثوابت البوت ====================
BOT_TOKEN = "8633990136:AAG-qSfAfFshk1yK_r-V6uNUIPJ4l6LKaIY"
ADMIN_IDS = [884089770]
SUPPORT_USER = "@SSOLTAAANNN"

# إعدادات الأداء
MAX_WORKERS = 50
CACHE_TTL = 300
DB_TIMEOUT = 30
DB_POOL_SIZE = 20

# ==================== تجمع قواعد البيانات ====================
class DatabasePool:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.pool = []
                    cls._instance.pool_lock = threading.Lock()
                    for _ in range(DB_POOL_SIZE):
                        conn = sqlite3.connect('bot.db', check_same_thread=False, timeout=DB_TIMEOUT)
                        conn.row_factory = sqlite3.Row
                        cls._instance.pool.append(conn)
        return cls._instance
    
    def get_connection(self):
        with self.pool_lock:
            if self.pool:
                return self.pool.pop()
            return sqlite3.connect('bot.db', check_same_thread=False, timeout=DB_TIMEOUT)
    
    def return_connection(self, conn):
        with self.pool_lock:
            self.pool.append(conn)

db_pool = DatabasePool()

def get_db():
    return db_pool.get_connection()

def return_db(conn):
    db_pool.return_connection(conn)

# ==================== الكاش ====================
cache: Dict[str, Tuple[Any, float]] = {}
cache_lock = threading.Lock()

def cache_get(key: str) -> Optional[Any]:
    with cache_lock:
        if key in cache:
            value, timestamp = cache[key]
            if time.time() - timestamp < CACHE_TTL:
                return value
            del cache[key]
    return None

def cache_set(key: str, value: Any) -> None:
    with cache_lock:
        cache[key] = (value, time.time())

def cache_clear(pattern: str = None) -> None:
    with cache_lock:
        if pattern is None:
            cache.clear()
        else:
            keys = [k for k in cache if pattern in k]
            for k in keys:
                del cache[k]

# ==================== قاعدة البيانات ====================
conn_main = sqlite3.connect('bot.db', check_same_thread=False, timeout=DB_TIMEOUT)
conn_main.row_factory = sqlite3.Row
c_main = conn_main.cursor()

# إنشاء الجداول
c_main.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    last_use TEXT,
    banned INTEGER DEFAULT 0,
    admin INTEGER DEFAULT 0,
    allowed INTEGER DEFAULT 0,
    created_at TEXT,
    total_requests INTEGER DEFAULT 0
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS allowed_users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    added_by INTEGER,
    added_date TEXT
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS user_platform (
    user_id INTEGER PRIMARY KEY,
    platform TEXT DEFAULT 'android'
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS games_af (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    display_name TEXT,
    package TEXT,
    dev_key TEXT,
    emoji TEXT
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS games_singular (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    display_name TEXT,
    package TEXT,
    app_key TEXT,
    emoji TEXT
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS games_adj (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    display_name TEXT,
    app_token TEXT,
    emoji TEXT
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS events_af (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    event_name TEXT,
    display_name TEXT,
    event_type TEXT,
    is_purchase INTEGER DEFAULT 0
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS events_singular (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    event_name TEXT,
    display_name TEXT,
    event_type TEXT
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS events_adj (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    event_name TEXT,
    event_token TEXT,
    display_name TEXT,
    level_value INTEGER
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE,
    proxy_type TEXT,
    proxy_host TEXT,
    proxy_port INTEGER,
    proxy_user TEXT,
    proxy_pass TEXT,
    created_date TEXT,
    last_used TEXT,
    usage_count INTEGER DEFAULT 0
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS farm_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    task_name TEXT UNIQUE,
    platform TEXT,
    game_id INTEGER,
    game_name TEXT,
    start_level INTEGER,
    end_level INTEGER,
    total_days INTEGER,
    mode TEXT,
    current_day INTEGER,
    current_level INTEGER,
    status TEXT,
    created_date TEXT,
    last_run TEXT,
    aifa TEXT,
    gaid TEXT,
    uid TEXT,
    af_uid TEXT,
    gps_adid TEXT,
    idfa TEXT,
    idfv TEXT,
    att_status INTEGER,
    completed_levels INTEGER DEFAULT 0,
    failed_attempts INTEGER DEFAULT 0
)''')

c_main.execute('''CREATE TABLE IF NOT EXISTS user_stats (
    user_id INTEGER PRIMARY KEY,
    last_daily_reset TEXT,
    daily_requests INTEGER DEFAULT 0,
    total_af_requests INTEGER DEFAULT 0,
    total_adj_requests INTEGER DEFAULT 0,
    total_singular_requests INTEGER DEFAULT 0
)''')

# إنشاء الفهارس
c_main.execute("CREATE INDEX IF NOT EXISTS idx_users_allowed ON users(allowed)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_farm_tasks_user ON farm_tasks(user_id)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_farm_tasks_status ON farm_tasks(status)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_events_af_game ON events_af(game_id)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_events_adj_game ON events_adj(game_id)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_events_singular_game ON events_singular(game_id)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_proxies_user ON proxies(user_id)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_user_platform ON user_platform(user_id)")
conn_main.commit()

# ==================== دوال نظام التشغيل ====================
def get_user_platform(user_id: int) -> str:
    result = c_main.execute("SELECT platform FROM user_platform WHERE user_id = ?", (user_id,)).fetchone()
    if result:
        return result[0]
    c_main.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?, ?)", (user_id, "android"))
    conn_main.commit()
    return "android"

def set_user_platform(user_id: int, platform: str) -> None:
    c_main.execute("INSERT OR REPLACE INTO user_platform (user_id, platform) VALUES (?, ?)", (user_id, platform))
    conn_main.commit()

# ==================== إضافة البيانات الأولية ====================

# حذف البيانات القديمة لتجنب التكرار
c_main.execute("DELETE FROM games_af")
c_main.execute("DELETE FROM events_af")
c_main.execute("DELETE FROM games_singular")
c_main.execute("DELETE FROM events_singular")
c_main.execute("DELETE FROM games_adj")
c_main.execute("DELETE FROM events_adj")
conn_main.commit()

# ==================== ألعاب AppsFlyer ====================
AF_GAMES = [
    ("dice_dream", "🎲 Dice Dreams", "com.superplaystudios.dicedreams", "Hn5qYjVAaRNJYDcwF4LaWF", "🎲"),
    ("domino_dreams", "🃏 Domino Dreams", "com.screenshake.dominodreams", "Hn5qYjVAaRNJYDcwF4LaWF", "🃏"),
    ("buzzle_chaos", "🎲 Buzzle Chaos", "com.global.pnck", "ZnhUvonKa6qF9xhgt7GcBQ", "🎲"),
    ("coin_master", "🎲 Coin Master", "com.moonactive.coinmaster", "H3KjoCRVTiVgA5mWSAHtCe", "🎲"),
    ("royal_match", "👑 Royal Match", "com.dreamgames.royalmatch", "B27HnbGEcbWC2fv79DDhcb", "👑"),
    ("merge_gardens", "🌺 Merge Gardens", "com.futureplay.mergematch", "nr8SibwpFjcKGBQNpDdttd", "🌺"),
    ("highroller_vegas", "🎲 HIGHROLLER Vegas", "com.lynxgames.hrv", "sSpBC5SKPKEV8fbZJgw6vM", "🎲"),
    ("rock_n_cash", "💰 Rock N Cash Casino", "net.flysher.rockncash", "W5VWPj5fbCGABtk59TsmJQ", "💰"),
    ("coinchef", "🍳 COINCHEF", "com.FortuneMine.CuisineMaster", "im6mgZbZJsHKGVowkkxkGm", "🍳"),
    ("blackjack21", "🃏 Blackjack 21", "com.kamagames.blackjack", "YbczyDZZmXbxwpYYyJgqTQ", "🃏"),
    ("sunshine_island", "🏝️ Sunshine Island", "com.newmoonproduction.sunshineisland", "FtaT5WH9rMJjJkMd4LfBCT", "🏝️"),
    ("farmville3", "🌾 Farmville 3", "com.zynga.FarmVille2CountryEscape", "438VCPmX2ZLYvsDPfGLZXb", "🌾"),
    ("disney_solitaire", "🎲 Disney Solitaire", "com.superplaystudios.disneysolitairedreams", "Hn5qYjVAaRNJYDcwF4LaWF", "🎲"),
    ("matching_story", "🎲 Matching Story", "com.joycastle.mergematch", "v2w2tuNCNaBNXvFJgRGPRW", "🎲"),
    ("nations_of_darkness", "🎲 Nations of Darkness", "com.allstarunion.nod", "x88hdqNmd8vALRmRMhgY4Q", "🎲"),
    ("hero_wars", "🎲 Hero Wars", "com.nexters.herowars", "MGPcVAUzD9XqbwAY6q7KMf", "🎲"),
    ("zombie_waves", "🧟 Zombie Waves", "com.ddup.zombiewaves.zw", "wiQMRPvGaAYTGBCgM5yN9N", "🧟"),
]

for game in AF_GAMES:
    c_main.execute("INSERT OR IGNORE INTO games_af (name, display_name, package, dev_key, emoji) VALUES (?, ?, ?, ?, ?)", game)

def add_af_events():
    # Dice Dreams
    dd = c_main.execute("SELECT id FROM games_af WHERE name = 'dice_dream'").fetchone()
    if dd:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (dd[0], "af_kingdom_3_restored", "🏰 Kingdom 3", "kingdom", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (dd[0], "af_kingdom_18_restored", "🏰 Kingdom 18", "kingdom", 0))
    
    # Domino Dreams
    dom = c_main.execute("SELECT id FROM games_af WHERE name = 'domino_dreams'").fetchone()
    if dom:
        for area in range(1, 6):
            c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                           (dom[0], f"af_area_{area}_completed", f"🗺️ Area {area}", "area", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (dom[0], "af_level_100_completed", "🏆 Level 100", "level", 0))
    
    # Royal Match
    rm = c_main.execute("SELECT id FROM games_af WHERE name = 'royal_match'").fetchone()
    if rm:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (rm[0], "level_3", "🏆 Level 3", "level", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (rm[0], "area_2", "🗺️ Area 2", "area", 0))
    
    # Merge Gardens
    mg = c_main.execute("SELECT id FROM games_af WHERE name = 'merge_gardens'").fetchone()
    if mg:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (mg[0], "Incent_Player_Level_Up_2", "⭐ Player Level Up 2", "level", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (mg[0], "Incent_IAP_gems2", "💎 IAP Gems 2", "purchase", 1))
    
    # HIGHROLLER Vegas
    hr = c_main.execute("SELECT id FROM games_af WHERE name = 'highroller_vegas'").fetchone()
    if hr:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (hr[0], "app_level_achieved_5", "🎯 Level 5", "level", 0))
    
    # Rock N Cash
    rnc = c_main.execute("SELECT id FROM games_af WHERE name = 'rock_n_cash'").fetchone()
    if rnc:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (rnc[0], "v3_rnc_level_up_10_S2S", "🎰 Level Up 10", "level", 0))
    
    # COINCHEF
    cc = c_main.execute("SELECT id FROM games_af WHERE name = 'coinchef'").fetchone()
    if cc:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (cc[0], "level2_completed", "🍳 Level 2 Completed", "level", 0))
    
    # Blackjack 21
    bj = c_main.execute("SELECT id FROM games_af WHERE name = 'blackjack21'").fetchone()
    if bj:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (bj[0], "30levelup", "🏆 Level 30", "level", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (bj[0], "2level", "🃏 Level 2", "level", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (bj[0], "5levelup", "🃏 Level 5", "level", 0))
    
    # Sunshine Island
    si = c_main.execute("SELECT id FROM games_af WHERE name = 'sunshine_island'").fetchone()
    if si:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (si[0], "af_level5_achieved", "🏝️ Level 5", "level", 0))
    
    # Farmville 3
    fv = c_main.execute("SELECT id FROM games_af WHERE name = 'farmville3'").fetchone()
    if fv:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (fv[0], "Player_Level9", "⭐ Level 9", "level", 0))
    
    # Coin Master
    cm = c_main.execute("SELECT id FROM games_af WHERE name = 'coin_master'").fetchone()
    if cm:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (cm[0], "village_1_complete", "🏠 Village 1 Complete", "level", 0))
    
    # Disney Solitaire
    ds = c_main.execute("SELECT id FROM games_af WHERE name = 'disney_solitaire'").fetchone()
    if ds:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (ds[0], "af_level_100_completed", "⭐ Level 100", "level", 0))
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (ds[0], "af_area_22_completed", "🗺️ Area 22", "area", 0))
    
    # Hero Wars
    hw = c_main.execute("SELECT id FROM games_af WHERE name = 'hero_wars'").fetchone()
    if hw:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (hw[0], "levelup5", "⭐ Level Up 5", "level", 0))
    
    # Zombie Waves
    zw = c_main.execute("SELECT id FROM games_af WHERE name = 'zombie_waves'").fetchone()
    if zw:
        c_main.execute("INSERT OR IGNORE INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)", 
                       (zw[0], "af_zw_lv5", "🧟 Level 5", "level", 0))

add_af_events()

# ==================== ألعاب Singular ====================
SINGULAR_GAMES = [
    ("animals_coins", "🦁 Animals & Coins", "com.innplaylabs.animalkingdomraid", "innplay_labs_33d87c9b", "🦁"),
    ("time_master", "⏰ Time Master", "com.firefog.timemaster", "myappfree_spa_38e49215", "⏰"),
    ("beast_go", "🐉 Beast Go", "com.ninthart.board.beastgo", "myappfree_spa_38e49215", "🐉"),
    ("coin_fantasy", "💰 Coin Fantasy", "com.okvision.coinfantasy", "myappfree_spa_38e49215", "💰"),
    ("dragon_farm", "🐉 Dragon Farm", "com.dragon.escape.island.adventure", "myappfree_spa_38e49215", "🐉"),
    ("box_cat_jam", "🐱 Box Cat Jam", "com.actionfit.blockcat", "actionfit_adc62229", "🐱"),
    ("idle_soap", "🧼 Idle Soap ASMR", "games.midnite.isa", "myappfree_spa_38e49215", "🧼"),
    ("superheroes_idle", "🦸 Superheroes Idle RPG", "games.midnite.sid", "myappfree_spa_38e49215", "🦸"),
    ("survivor_idle", "🏃 Survivor Idle Run", "games.midnite.sri", "myappfree_spa_38e49215", "🏃"),
    ("pop_slots", "🎰 POP Slots", "com.playstudios.popslots", "playstudios_3852f898", "🎰"),
    ("mgm_slots", "🎰 MGM Slots Live", "com.playstudios.showstar", "playstudios_3852f898", "🎰"),
    ("myvegas", "🎰 myVEGAS Slots", "com.playstudios.myvegas", "playstudios_3852f898", "🎰"),
    ("power_spin", "💪 Power Spin Quest", "com.braingames.powerquest", "brain_games_a7dde873", "💪"),
    ("sweet_jam", "🍯 Sweet Jam!", "puzzle.game.sweetjam", "myappfree_spa_38e49215", "🍯"),
    ("matching_go", "🔗 Matching Go!", "com.matchinggo.puzzlegames", "xinagyi_f4545a5d", "🔗"),
    ("screw_out", "🔧 Screw Out Factory 3D", "com.ntt.screw.out.factory", "puzzle_studios_4d38bec9", "🔧"),
    ("hole_collect", "🕳️ Hole Collect", "com.ntt.hole.collect.objects", "puzzle_studios_4d38bec9", "🕳️"),
    ("tetris_block", "🧩 Tetris Block Party", "com.playstudios.tetrisblockparty", "playstudios_3852f898", "🧩"),
    ("word_madness", "📖 Word Madness", "com.word.madness", "brain_games_a7dde873", "📖"),
    ("word_wise", "📖 Word Wise", "com.playx.wordwise.crossword", "myappfree_spa_38e49215", "📖"),
    ("eatventure", "🍔 Eatventure", "com.hwqgrhhjfd.idlefastfood", "lessmore_edff53fc", "🍔"),
]

for game in SINGULAR_GAMES:
    c_main.execute("INSERT OR IGNORE INTO games_singular (name, display_name, package, app_key, emoji) VALUES (?, ?, ?, ?, ?)", game)

def add_singular_events():
    # Animals & Coins
    ac = c_main.execute("SELECT id FROM games_singular WHERE name = 'animals_coins'").fetchone()
    if ac:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (ac[0], "Reach Level 3", "⏰ leve 3", "level"))
    
    # Time Master
    tm = c_main.execute("SELECT id FROM games_singular WHERE name = 'time_master'").fetchone()
    if tm:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (tm[0], "mn_location_1", "⏰ location 1", "level"))
    
    # Beast Go
    bg = c_main.execute("SELECT id FROM games_singular WHERE name = 'beast_go'").fetchone()
    if bg:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (bg[0], "sng_level_achieved", "🐉 sng_level_achieved", "level"))
    
    # Coin Fantasy
    cf = c_main.execute("SELECT id FROM games_singular WHERE name = 'coin_fantasy'").fetchone()
    if cf:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (cf[0], "mn_level_", "💰 mn_level_", "level"))
    
    # Dragon Farm
    df = c_main.execute("SELECT id FROM games_singular WHERE name = 'dragon_farm'").fetchone()
    if df:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (df[0], "mn_level_", "🐉 mn_level_", "level"))
    
    # Box Cat Jam
    bcj = c_main.execute("SELECT id FROM games_singular WHERE name = 'box_cat_jam'").fetchone()
    if bcj:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (bcj[0], "First_attempt_level_", "🐱 First_attempt_level_", "level"))
    
    # Idle Soap
    ids = c_main.execute("SELECT id FROM games_singular WHERE name = 'idle_soap'").fetchone()
    if ids:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (ids[0], "soap_unlocked", "🧼 soap_unlocked", "unlock"))
    
    # Superheroes Idle
    shi = c_main.execute("SELECT id FROM games_singular WHERE name = 'superheroes_idle'").fetchone()
    if shi:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (shi[0], "mn_cheater_level_achieved", "🦸 mn_cheater_level_achieved", "level"))
    
    # Survivor Idle
    sui = c_main.execute("SELECT id FROM games_singular WHERE name = 'survivor_idle'").fetchone()
    if sui:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (sui[0], "sng_level_achieved", "🏃 sng_level_achieved", "level"))
    
    # POP Slots, MGM Slots, myVEGAS
    ps = c_main.execute("SELECT id FROM games_singular WHERE name = 'pop_slots'").fetchone()
    if ps:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (ps[0], "level", "🎰 level", "level"))
    
    mgm = c_main.execute("SELECT id FROM games_singular WHERE name = 'mgm_slots'").fetchone()
    if mgm:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (mgm[0], "level", "🎰 level", "level"))
    
    mv = c_main.execute("SELECT id FROM games_singular WHERE name = 'myvegas'").fetchone()
    if mv:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (mv[0], "level", "🎰 level", "level"))
    
    # Power Spin
    pws = c_main.execute("SELECT id FROM games_singular WHERE name = 'power_spin'").fetchone()
    if pws:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (pws[0], "level_ended_", "💪 level_ended_", "level"))
    
    # Sweet Jam
    sj = c_main.execute("SELECT id FROM games_singular WHERE name = 'sweet_jam'").fetchone()
    if sj:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (sj[0], "sng_level_achieved", "🍯 sng_level_achieved", "level"))
    
    # Matching Go
    mgo = c_main.execute("SELECT id FROM games_singular WHERE name = 'matching_go'").fetchone()
    if mgo:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (mgo[0], "user_level_complete_", "🔗 user_level_complete_", "level"))
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (mgo[0], "ad_show_", "📺 ad_show_", "ad"))
    
    # Hole Collect
    hc = c_main.execute("SELECT id FROM games_singular WHERE name = 'hole_collect'").fetchone()
    if hc:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (hc[0], "map_unlocked", "🗺️ map_unlocked", "unlock"))
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (hc[0], "sng_level_achieved", "🕳️ sng_level_achieved", "level"))
    
    # Tetris Block
    tb = c_main.execute("SELECT id FROM games_singular WHERE name = 'tetris_block'").fetchone()
    if tb:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (tb[0], "level_", "🧩 level_", "level"))
    
    # Word Madness
    wm = c_main.execute("SELECT id FROM games_singular WHERE name = 'word_madness'").fetchone()
    if wm:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (wm[0], "_levels_completed", "📖 _levels_completed", "level"))
    
    # Word Wise
    ww = c_main.execute("SELECT id FROM games_singular WHERE name = 'word_wise'").fetchone()
    if ww:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (ww[0], "mn_level_", "📖 mn_level_", "level"))
    
    # Eatventure
    ev = c_main.execute("SELECT id FROM games_singular WHERE name = 'eatventure'").fetchone()
    if ev:
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (ev[0], "restaurant_unlocked", "🍔 restaurant_unlocked", "unlock"))
        c_main.execute("INSERT OR IGNORE INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)", 
                       (ev[0], "lm_restaurant_completion", "🍔 lm_restaurant_completion", "complete"))

add_singular_events()

# ==================== ألعاب Adjust ====================
ADJ_GAMES = [
    ("get_color", "🎨 Get Color", "367kicwptj5s", "🎨"),
    ("merge_blocks", "🔲 2048 X2 Merge Blocks", "367kicwptj5s", "🔲"),
    ("puzzle2248", "🧩 2248 Puzzle", "367kicwptj5s", "🧩"),
    ("alice_blastland", "🌸 Alice in Blastland", "367kicwptj5s", "🌸"),
    ("army_tycoon", "🎖️ Army Tycoon", "367kicwptj5s", "🎖️"),
    ("battle_night", "⚔️ Battle Night", "367kicwptj5s", "⚔️"),
    ("berry_factory", "🍓 Berry Factory Tycoon", "367kicwptj5s", "🍓"),
    ("big_card_solitaire", "🃏 Big Card Solitaire", "367kicwptj5s", "🃏"),
    ("bingo_aloha", "🍍 Bingo Aloha", "367kicwptj5s", "🍍"),
    ("bingo_showdown", "🎯 Bingo Showdown", "367kicwptj5s", "🎯"),
    ("blast_friends", "💥 Blast Friends", "367kicwptj5s", "💥"),
    ("block_blitz", "🧱 Block Blitz", "367kicwptj5s", "🧱"),
    ("block_joy", "🎮 Block Joy Puzzle", "367kicwptj5s", "🎮"),
    ("gems_adventure", "💎 Gems Adventure", "367kicwptj5s", "💎"),
    ("bravo_slots", "🎰 Bravo Classic Slots", "367kicwptj5s", "🎰"),
    ("cash_storm", "🌪️ Cash Storm", "367kicwptj5s", "🌪️"),
    ("climb_mountain", "⛰️ Climb the Mountain", "367kicwptj5s", "⛰️"),
    ("clock_maker", "⏰ Clock Maker", "367kicwptj5s", "⏰"),
    ("clone_evolution", "🧬 Clone Evolution", "367kicwptj5s", "🧬"),
    ("clubbillion", "🎲 Clubbillion Vegas", "367kicwptj5s", "🎲"),
    ("color_water_sort", "🎨 Color Water Sort", "367kicwptj5s", "🎨"),
]

for game in ADJ_GAMES:
    c_main.execute("INSERT OR IGNORE INTO games_adj (name, display_name, app_token, emoji) VALUES (?, ?, ?, ?)", game)

def add_adj_events():
    # Get Color
    gc = c_main.execute("SELECT id FROM games_adj WHERE name = 'get_color'").fetchone()
    if gc:
        gid = gc[0]
        levels = [(15, "8t8nb3"), (30, "uwq9v8"), (50, "fdlgyk"), (75, "dwhyjz"), (80, "34vgez"),
                  (100, "txq8if"), (120, "lwhvaj"), (150, "iatv2g"), (200, "stpy1k"), (300, "53lena"),
                  (400, "dbdy8l"), (500, "3i4yf5"), (700, "pwd51u"), (1000, "4o9jbt")]
        for lvl, token in levels:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, f"level_{lvl}", token, f"🏆 Level {lvl}", lvl))
    
    
    # 2048 X2 Merge Blocks
    mb = c_main.execute("SELECT id FROM games_adj WHERE name = 'merge_blocks'").fetchone()
    if mb:
        gid = mb[0]
        events = [
            ("event_callback_yd6777", "yd6777", "Reach step 5", 5),
            ("event_callback_8mpa1x", "8mpa1x", "Step 10", 10),
            ("event_callback_j9tstz", "j9tstz", "Step 25", 25),
            ("event_callback_g3mipt", "g3mipt", "Step 50", 50),
            ("event_callback_v197np", "v197np", "Step 100", 100),
            ("event_callback_vbwc0z", "vbwc0z", "Step 250", 250),
            ("event_callback_j7pzey", "j7pzey", "Step 500", 500),
            ("event_callback_47euyf", "47euyf", "Step 1000", 1000),
            ("event_callback_jom3es", "jom3es", "Make a purchase", 0),
            ("event_callback_2i73t2", "2i73t2", "Purchase", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # 2248 Puzzle
    pz = c_main.execute("SELECT id FROM games_adj WHERE name = 'puzzle2248'").fetchone()
    if pz:
        gid = pz[0]
        events = [
            ("event_callback_lumf2i", "lumf2i", "Level 10", 10),
            ("event_callback_p08k2f", "p08k2f", "Level 25", 25),
            ("event_callback_cciiv6", "cciiv6", "Level 50", 50),
            ("event_callback_yysyts", "yysyts", "Level 100", 100),
            ("event_callback_dhwefa", "dhwefa", "Level 250", 250),
            ("event_callback_hn8yew", "hn8yew", "Level 500", 500),
            ("event_callback_igqmwt", "igqmwt", "Level 1000", 1000),
            ("event_callback_236tr52", "236tr52", "Session", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Alice in Blastland
    al = c_main.execute("SELECT id FROM games_adj WHERE name = 'alice_blastland'").fetchone()
    if al:
        gid = al[0]
        events = [
            ("event_callback_uefzz6", "uefzz6", "Reach Level 5", 5),
            ("event_callback_15h2c4", "15h2c4", "Level 15", 15),
            ("event_callback_x2o8is", "x2o8is", "First time deposit", 0),
            ("event_callback_dndphq", "dndphq", "Reach Level 30", 30),
            ("event_callback_5oolhi", "5oolhi", "Reach Level 50", 50),
            ("event_callback_l5p54c", "l5p54c", "Reach Level 100", 100),
            ("event_callback_yhj1lm", "yhj1lm", "Level 200", 200),
            ("event_callback_i4juxt", "i4juxt", "Level 300", 300),
            ("event_callback_oftnes", "oftnes", "Level 500", 500),
            ("event_callback_z8ovou", "z8ovou", "Level 750", 750),
            ("event_callback_qww7m6", "qww7m6", "Level 1000", 1000),
            ("event_callback_25764", "25764", "Session", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Army Tycoon
    at = c_main.execute("SELECT id FROM games_adj WHERE name = 'army_tycoon'").fetchone()
    if at:
        gid = at[0]
        events = [
            ("event_callback_ucfrab", "ucfrab", "Unlock Artillery Course", 1),
            ("event_callback_kcii8f", "kcii8f", "Unlock Tank Course", 2),
            ("event_callback_1tgiij", "1tgiij", "Unlock Indoor Shooting Range", 3),
            ("event_callback_x2b508", "x2b508", "Unlock Helicopter Course", 4),
            ("event_callback_afpgpn", "afpgpn", "Event", 5),
            ("event_callback_24260", "24260", "Session", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Battle Night
    bn = c_main.execute("SELECT id FROM games_adj WHERE name = 'battle_night'").fetchone()
    if bn:
        gid = bn[0]
        events = [
            ("event_callback_wdu1px", "wdu1px", "Collect 2 Purple Heroes", 2),
            ("event_callback_at7h8t", "at7h8t", "Purchase Month Card", 0),
            ("event_callback_f6z6gr", "f6z6gr", "Complete Chapter 6", 6),
            ("event_callback_8no4ma", "8no4ma", "Buy Login Premium Pass", 0),
            ("event_callback_jb6urh", "jb6urh", "Collect 1 Orange Hero", 1),
            ("event_callback_lltjkz", "lltjkz", "2 Orange Hero", 2),
            ("event_callback_9dy8xg", "9dy8xg", "4 Orange Hero", 4),
            ("event_callback_z8vm09", "z8vm09", "6 Orange Hero", 6),
            ("event_callback_98bp74", "98bp74", "9 Orange Hero", 9),
            ("event_callback_9aqu0l", "9aqu0l", "Reach VIP Level 4", 4),
            ("event_callback_36w4u0", "36w4u0", "12 Orange Hero", 12),
            ("event_callback_xjcc3q", "xjcc3q", "15 Orange Hero", 15),
            ("event_callback_4g2o7u", "4g2o7u", "1 Red Hero", 1)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Berry Factory
    bf = c_main.execute("SELECT id FROM games_adj WHERE name = 'berry_factory'").fetchone()
    if bf:
        gid = bf[0]
        events = [
            ("event_callback_vex04j", "vex04j", "Reach Dessert Factory", 1),
            ("event_callback_f28p6w", "f28p6w", "Reach Candy Combine", 2),
            ("event_callback_rsrv4q", "rsrv4q", "Reach Jelly Concern", 3),
            ("event_callback_rktc9a", "rktc9a", "Upgrade Glazer to Maximum", 4),
            ("event_callback_32t74", "32t74", "Session", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Big Card Solitaire
    bcs = c_main.execute("SELECT id FROM games_adj WHERE name = 'big_card_solitaire'").fetchone()
    if bcs:
        gid = bcs[0]
        events = [
            ("event_callback_y0oh58", "y0oh58", "First Time Deposit", 0),
            ("event_callback_58fm8f", "58fm8f", "Reach Level 15", 15),
            ("event_callback_iecaaf", "iecaaf", "Level 20", 20),
            ("event_callback_i31lvg", "i31lvg", "Level 30", 30),
            ("event_callback_vjrg9q", "vjrg9q", "Collect 3K Coins", 3000),
            ("event_callback_1fiiml", "1fiiml", "Collect 5K Coins", 5000),
            ("event_callback_rbxsf1", "rbxsf1", "Collect 7K Coins", 7000),
            ("event_callback_i4avja", "i4avja", "10K Coins", 10000),
            ("event_callback_j2y6j9", "j2y6j9", "20K Coins", 20000),
            ("event_callback_r5um2u", "r5um2u", "50K Coins", 50000),
            ("event_callback_bbyp36", "bbyp36", "100K Coins", 100000),
            ("event_callback_b8gfs7", "b8gfs7", "200K Coins", 200000),
            ("event_callback_rb2zo3", "rb2zo3", "400K Coins", 400000)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Bingo Aloha
    ba = c_main.execute("SELECT id FROM games_adj WHERE name = 'bingo_aloha'").fetchone()
    if ba:
        gid = ba[0]
        events = [
            ("event_callback_tr4vq2", "tr4vq2", "Reach Level 20", 20),
            ("event_callback_f82iiq", "f82iiq", "Level 30", 30),
            ("event_callback_ifxzih", "ifxzih", "Level 40", 40),
            ("event_callback_3yza9s", "3yza9s", "Level 50", 50),
            ("event_callback_pk6qyf", "pk6qyf", "Bonus: Level 60 within 3 days", 60),
            ("event_callback_w5tltt", "w5tltt", "Level 80", 80),
            ("event_callback_189lri", "189lri", "Level 120", 120),
            ("event_callback_3g5fjn", "3g5fjn", "Level 150", 150),
            ("event_callback_2vj74s", "2vj74s", "Bonus: Level 200 within 6 days", 200),
            ("event_callback_ccm57s", "ccm57s", "Level 300", 300),
            ("event_callback_pxvvbe", "pxvvbe", "Level 400", 400),
            ("event_callback_uqst83", "uqst83", "Level 500", 500),
            ("event_callback_3wfbqv", "3wfbqv", "Purchase $19.9", 0),
            ("event_callback_ckugaz", "ckugaz", "Purchase $9.99", 0),
            ("event_callback_uvz4f0", "uvz4f0", "Purchase $4.99", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Bingo Showdown
    bs = c_main.execute("SELECT id FROM games_adj WHERE name = 'bingo_showdown'").fetchone()
    if bs:
        gid = bs[0]
        events = [
            ("event_callback_w10qxm", "w10qxm", "First Bingo", 1),
            ("event_callback_3jdb4n", "3jdb4n", "Reach Level 2", 2),
            ("event_callback_njnr15", "njnr15", "Level 3", 3),
            ("event_callback_2sv8qt", "2sv8qt", "Level 5", 5),
            ("event_callback_14h0b2", "14h0b2", "Level 10", 10),
            ("event_callback_livykp", "livykp", "Level 15", 15),
            ("event_callback_95ye13", "95ye13", "Level 20", 20),
            ("event_callback_fjp3vm", "fjp3vm", "Level 25", 25),
            ("event_callback_upmo7s", "upmo7s", "Level 50", 50),
            ("event_callback_jkpze3", "jkpze3", "First Purchase", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Blast Friends
    bf2 = c_main.execute("SELECT id FROM games_adj WHERE name = 'blast_friends'").fetchone()
    if bf2:
        gid = bf2[0]
        events = [
            ("event_callback_v5zsay", "v5zsay", "Reach Level 20", 20),
            ("event_callback_qco1yc", "qco1yc", "Level 50", 50),
            ("event_callback_nmbpbj", "nmbpbj", "Level 100", 100),
            ("event_callback_7tcb9y", "7tcb9y", "Level 250", 250),
            ("event_callback_a0tksk", "a0tksk", "Level 500", 500),
            ("event_callback_r9ojpu", "r9ojpu", "Level 1000", 1000),
            ("event_callback_8q1rrv", "8q1rrv", "Level 2000", 2000)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Block Blitz
    bb2 = c_main.execute("SELECT id FROM games_adj WHERE name = 'block_blitz'").fetchone()
    if bb2:
        gid = bb2[0]
        events = [
            ("event_callback_z9gmw7", "z9gmw7", "Win Journey Level 5", 5),
            ("event_callback_erj7x3", "erj7x3", "Level 10", 10),
            ("event_callback_1v5jpk", "1v5jpk", "Level 20", 20),
            ("event_callback_1puzhk", "1puzhk", "Level 30", 30),
            ("event_callback_fxhwo0", "fxhwo0", "Level 40", 40),
            ("event_callback_bqkl2c", "bqkl2c", "Level 50", 50),
            ("event_callback_tum80y", "tum80y", "Level 70", 70),
            ("event_callback_nm5hzf", "nm5hzf", "Level 100", 100),
            ("event_callback_ulzxtz", "ulzxtz", "Level 150", 150),
            ("event_callback_q7kns1", "q7kns1", "Level 300", 300),
            ("event_callback_uf24fv", "uf24fv", "Level 500", 500),
            ("event_callback_vjp76b", "vjp76b", "Level 700", 700),
            ("event_callback_nxjpvy", "nxjpvy", "Level 1000", 1000),
            ("event_callback_1020304", "1020304", "First Time Purchase", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Block Joy
    bj2 = c_main.execute("SELECT id FROM games_adj WHERE name = 'block_joy'").fetchone()
    if bj2:
        gid = bj2[0]
        events = [
            ("event_callback_dvo8mu", "dvo8mu", "Level 5", 5),
            ("event_callback_r45ld3", "r45ld3", "Level 10", 10),
            ("event_callback_61mki6", "61mki6", "Level 20", 20),
            ("event_callback_15q1fg", "15q1fg", "Level 30", 30),
            ("event_callback_1ziiag", "1ziiag", "Level 50", 50),
            ("event_callback_yh508k", "yh508k", "Level 70", 70),
            ("event_callback_3gxgyp", "3gxgyp", "Level 100", 100),
            ("event_callback_vev8ur", "vev8ur", "Level 150", 150),
            ("event_callback_nazx5v", "nazx5v", "Level 300", 300),
            ("event_callback_q98rl6", "q98rl6", "Level 500", 500),
            ("event_callback_v1htdn", "v1htdn", "Level 700", 700),
            ("event_callback_soa9vy", "soa9vy", "Level 1000", 1000),
            ("event_callback_c8ck9d", "c8ck9d", "First Purchase", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Gems Adventure
    ga = c_main.execute("SELECT id FROM games_adj WHERE name = 'gems_adventure'").fetchone()
    if ga:
        gid = ga[0]
        events = [
            ("event_callback_dwowyx", "dwowyx", "Score 3K", 3000),
            ("event_callback_h2e11l", "h2e11l", "Score 5K", 5000),
            ("event_callback_25ud1c", "25ud1c", "Score 10K", 10000),
            ("event_callback_3vdhft", "3vdhft", "Score 25K", 25000),
            ("event_callback_amhlay", "amhlay", "Score 50K", 50000),
            ("event_callback_mkuzzm", "mkuzzm", "Score 100K", 100000),
            ("event_callback_nyi04s", "nyi04s", "Score 250K", 250000),
            ("event_callback_1v45em", "1v45em", "Score 500K", 500000),
            ("event_callback_q3tfto", "q3tfto", "Score 750K", 750000),
            ("event_callback_o9d9hb", "o9d9hb", "Score 1M", 1000000)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Bravo Slots
    br = c_main.execute("SELECT id FROM games_adj WHERE name = 'bravo_slots'").fetchone()
    if br:
        gid = br[0]
        events = [
            ("event_callback_pxnk4e", "pxnk4e", "Reach Level 40", 40),
            ("event_callback_k6p17i", "k6p17i", "Reach Level 100", 100),
            ("event_callback_fw0837", "fw0837", "Purchase Mission Pass", 0),
            ("event_callback_i1l8xp", "i1l8xp", "Reach Level 200", 200),
            ("event_callback_nlql3m", "nlql3m", "Reach Level 400", 400),
            ("event_callback_1pvoa2", "1pvoa2", "Accum Purchase $9.99", 0),
            ("event_callback_96j1vw", "96j1vw", "Reach Level 800", 800),
            ("event_callback_jpw7pe", "jpw7pe", "Level 2000", 2000),
            ("event_callback_y85bjt", "y85bjt", "Level 4000", 4000)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Cash Storm
    cs = c_main.execute("SELECT id FROM games_adj WHERE name = 'cash_storm'").fetchone()
    if cs:
        gid = cs[0]
        events = [
            ("event_callback_ht80ad", "ht80ad", "Complete Level 15", 15),
            ("event_callback_ll59t0", "ll59t0", "Purchase any $9.99", 0),
            ("event_callback_47akr5", "47akr5", "Level 30", 30),
            ("event_callback_yjd7i0", "yjd7i0", "Level 40", 40),
            ("event_callback_fmwgmq", "fmwgmq", "Level 60", 60),
            ("event_callback_6nulf0", "6nulf0", "Purchase any $19.9", 0),
            ("event_callback_6ppgib", "6ppgib", "Level 80", 80),
            ("event_callback_qyasgc", "qyasgc", "Level 100", 100)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Climb Mountain
    cm = c_main.execute("SELECT id FROM games_adj WHERE name = 'climb_mountain'").fetchone()
    if cm:
        gid = cm[0]
        events = [
            ("event_callback_xt4epl", "xt4epl", "Complete Level 25", 25),
            ("event_callback_n2qh1u", "n2qh1u", "Level 100", 100),
            ("event_callback_bssey9", "bssey9", "Level 300", 300)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))
    
    # Clock Maker
    ckm = c_main.execute("SELECT id FROM games_adj WHERE name = 'clock_maker'").fetchone()
    if ckm:
        gid = ckm[0]
        events = [
            ("event_callback_uu8lcy", "uu8lcy", "Unlock Stables", 1),
            ("event_callback_64yi1x", "64yi1x", "Unlock the Mill", 2),
            ("event_callback_gwqs4i", "gwqs4i", "Unlock Old Sam's House", 3),
            ("event_callback_uqry54", "uqry54", "Unlock Harrison's Mansion", 4),
            ("event_callback_1nwuqr", "1nwuqr", "Unlock Fire Station", 5),
            ("event_callback_as93wo", "as93wo", "Unlock Antique Shop", 6),
            ("event_callback_86t122", "86t122", "Unlock Theatre", 7),
            ("event_callback_t912za", "t912za", "Unlock School", 8),
            ("event_callback_senibm", "senibm", "Unlock Fountain", 9),
            ("event_callback_g8g4p2", "g8g4p2", "Unlock the Clock Tower", 10),
            ("event_callback_bev80p", "bev80p", "Purchase", 0)
        ]
        for ev in events:
            c_main.execute("INSERT OR IGNORE INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                           (gid, ev[0], ev[1], ev[2], ev[3]))

add_adj_events()

# إضافة المديرين
c_main.execute("INSERT OR IGNORE INTO users (user_id, username, name, admin, allowed, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               (6075014046, "admin", "Admin", 1, 1, datetime.now().isoformat()))
c_main.execute("INSERT OR IGNORE INTO allowed_users (user_id, username, name, added_by, added_date) VALUES (?, ?, ?, ?, ?)",
               (6075014046, "admin", "Admin", 6075014046, datetime.now().isoformat()))
c_main.execute("INSERT OR IGNORE INTO users (user_id, username, name, admin, allowed, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               (8114043468, "admin2", "Admin2", 1, 1, datetime.now().isoformat()))
c_main.execute("INSERT OR IGNORE INTO allowed_users (user_id, username, name, added_by, added_date) VALUES (?, ?, ?, ?, ?)",
               (8114043468, "admin2", "Admin2", 6075014046, datetime.now().isoformat()))
c_main.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?, ?)", (6075014046, "android"))
c_main.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?, ?)", (8114043468, "android"))
conn_main.commit()

cache_clear()

# ==================================================================================
#                               دوال مساعدة
# ==================================================================================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@lru_cache(maxsize=10000)
def is_allowed_cached(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    result = c_main.execute("SELECT user_id FROM allowed_users WHERE user_id = ?", (user_id,)).fetchone()
    return result is not None

def is_allowed(user_id: int) -> bool:
    return is_allowed_cached(user_id)

def add_allowed_user(user_id: int, username: str, name: str, admin_id: int) -> None:
    c_main.execute("INSERT OR IGNORE INTO allowed_users (user_id, username, name, added_by, added_date) VALUES (?, ?, ?, ?, ?)",
                   (user_id, username, name, admin_id, datetime.now().isoformat()))
    c_main.execute("UPDATE users SET allowed = 1 WHERE user_id = ?", (user_id,))
    conn_main.commit()
    is_allowed_cached.cache_clear()

def remove_allowed_user(user_id: int) -> None:
    c_main.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
    c_main.execute("UPDATE users SET allowed = 0 WHERE user_id = ?", (user_id,))
    conn_main.commit()
    is_allowed_cached.cache_clear()

def get_allowed_users():
    return c_main.execute("SELECT user_id, username, name, added_date FROM allowed_users").fetchall()

def get_all_games_af():
    cached = cache_get("games_af")
    if cached:
        return cached
    games = c_main.execute("SELECT id, name, display_name, package, dev_key, emoji FROM games_af").fetchall()
    cache_set("games_af", games)
    return games

def get_all_games_singular():
    cached = cache_get("games_singular")
    if cached:
        return cached
    games = c_main.execute("SELECT id, name, display_name, package, app_key, emoji FROM games_singular").fetchall()
    cache_set("games_singular", games)
    return games

def get_all_games_adj():
    cached = cache_get("games_adj")
    if cached:
        return cached
    games = c_main.execute("SELECT id, name, display_name, app_token, emoji FROM games_adj").fetchall()
    cache_set("games_adj", games)
    return games

def get_af_events(game_id: int, purchase_only: bool = False):
    key = f"af_events_{game_id}_{purchase_only}"
    cached = cache_get(key)
    if cached:
        return cached
    if purchase_only:
        events = c_main.execute("SELECT id, event_name, display_name FROM events_af WHERE game_id = ? AND is_purchase = 1", (game_id,)).fetchall()
    else:
        events = c_main.execute("SELECT id, event_name, display_name FROM events_af WHERE game_id = ? AND is_purchase = 0", (game_id,)).fetchall()
    cache_set(key, events)
    return events

def get_singular_events(game_id: int):
    key = f"singular_events_{game_id}"
    cached = cache_get(key)
    if cached:
        return cached
    events = c_main.execute("SELECT id, event_name, display_name FROM events_singular WHERE game_id = ?", (game_id,)).fetchall()
    cache_set(key, events)
    return events

def get_adj_events(game_id: int):
    key = f"adj_events_{game_id}"
    cached = cache_get(key)
    if cached:
        return cached
    events = c_main.execute("SELECT id, event_name, event_token, display_name, level_value FROM events_adj WHERE game_id = ? ORDER BY level_value", (game_id,)).fetchall()
    cache_set(key, events)
    return events

def get_user_by_identifier(identifier: str):
    if identifier.startswith("@"):
        username = identifier[1:]
        return c_main.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
    try:
        uid = int(identifier)
        return (uid,)
    except:
        return None

def increment_user_requests(user_id: int):
    c_main.execute("UPDATE users SET total_requests = total_requests + 1, last_use = ? WHERE user_id = ?",
                   (datetime.now().isoformat(), user_id))
    conn_main.commit()

# ==================================================================================
#                               دوال البروكسي
# ==================================================================================
def save_proxy(user_id: int, proxy_type: str, proxy_host: str, proxy_port: int, proxy_user: str, proxy_pass: str):
    c_main.execute("INSERT OR REPLACE INTO proxies (user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, datetime.now().isoformat()))
    conn_main.commit()

def delete_proxy(user_id: int):
    c_main.execute("DELETE FROM proxies WHERE user_id = ?", (user_id,))
    conn_main.commit()

def get_proxy_info(user_id: int):
    return c_main.execute("SELECT proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass FROM proxies WHERE user_id = ?", (user_id,)).fetchone()

def get_proxy_for_user(user_id: int) -> Optional[Dict[str, str]]:
    proxy_info = get_proxy_info(user_id)
    if not proxy_info:
        return None
    proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass = proxy_info
    proxies = {}
    if proxy_type in ("http", "https"):
        auth = f"{proxy_user}:{proxy_pass}@" if proxy_user and proxy_pass else ""
        proxies[proxy_type] = f"{proxy_type}://{auth}{proxy_host}:{proxy_port}"
    elif proxy_type == "socks5":
        auth = f"{proxy_user}:{proxy_pass}@" if proxy_user and proxy_pass else ""
        proxies["socks5"] = f"socks5://{auth}{proxy_host}:{proxy_port}"
    return proxies

# ==================================================================================
#                             إشعارات المزرعة
# ==================================================================================
async def send_farm_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int, task_id: int, level_hit: int, remaining: int, total: int, game_name: str):
    try:
        msg = (
            f"🌾 *تحديث المزرعة* 🌾\n\n"
            f"🎮 اللعبة: `{game_name}`\n"
            f"✅ تم ضرب المستوى: `{level_hit}`\n"
            f"📊 المتبقي: `{remaining}` مستوى\n"
            f"🎯 الإجمالي: `{total}` مستوى"
        )
        await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"فشل إرسال إشعار المزرعة: {e}")

# ==================================================================================
#                             دوال الإرسال
# ==================================================================================
# ==================================================================================
#                             دوال الإرسال
# ==================================================================================
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def send_af(pkg: str, dev_key: str, gaid: str, af_uid: str, event_name: str, revenue: float = None, proxy: Dict = None, platform: str = "android", idfa: str = None, idfv: str = None, custom_level: str = None) -> Tuple[int, str]:
    import random
    import uuid
    import time
    import requests
    
    # 🔥 التحقق من وجود البيانات
    if not pkg or pkg == "None" or pkg is None:
        print(f"[ERROR] ❌ Package is None or empty!")
        print(f"[ERROR] pkg value: {pkg}")
        return 400, "Error: Package name is required"
    
    if not dev_key:
        print(f"[ERROR] ❌ Dev Key is None or empty!")
        return 400, "Error: Dev Key is required"
    
    print(f"[DEBUG] ✅ Send AF - Package: {pkg}, Event: {event_name}")
    
    url = f"https://api2.appsflyer.com/inappevent/{pkg}"
    current_ts = int(time.time() * 1000)
    
    # باقي الكود مثل ما هو...
    
    # ❌ إذا كان pkg فارغ أو None، أرجِع خطأ فوري
    if not pkg or pkg == "None":
        print(f"[ERROR] Package name is empty or None!")
        return 400, "Package name is required"
    
    url = f"https://api2.appsflyer.com/inappevent/{pkg}"
    current_ts = int(time.time() * 1000)
    
    # ... باقي الكود نفس ما هو ...
    
    # ========== بيانات ثابتة (نفس اللي حسب) ==========
    DEVICE_MODEL = "SM-S911B"
    OS_VERSION = "Android 14"
    SDK_VERSION = "6.15.0"
    APP_VERSION = "2.3.0"
    
    # ========== بناء البايلود (نفس اللي حسب) ==========
    payload = {
        "appsflyer_id": af_uid,
        "advertising_id": gaid,
        "eventName": event_name,
        "eventTime": current_ts,
        "eventValue": {},
        "device_model": DEVICE_MODEL,
        "os_version": OS_VERSION,
        "sdk_version": SDK_VERSION,
        "app_version_name": APP_VERSION,
        "network": "WiFi",
        "language": "en-US",
        "timezone": "Asia/Riyadh"
    }
    
    if revenue:
        payload["eventRevenue"] = str(revenue)
        payload["eventCurrency"] = "USD"
        payload["eventValue"] = {
            "af_content_id": f"combo_{random.randint(1,50)}",
            "af_content_type": "purchase",
            "af_receipt_id": str(uuid.uuid4()),
            "af_transaction_id": str(uuid.uuid4()),
            "af_currency": "USD",
            "af_price": str(revenue)
        }
    else:
        # للأحداث العادية (زي المستويات)
        level_num = ''.join(filter(str.isdigit, event_name))
        # في حال أراد الزبون تحديد رقم لفل مخصص يدوياً نستخدمه مباشرة
        if custom_level:
            level_num = custom_level
        if level_num:
            payload["eventValue"] = {
                "af_level": level_num,
                "af_score": str(random.randint(1000, 50000)),
                "af_duration": str(random.randint(30, 300))
            }
    
    # ========== الهيدرز (نفس اللي حسب) ==========
    headers = {
        "Authentication": dev_key,
        "User-Agent": f"AppsFlyer-Android-SDK/{SDK_VERSION} (Linux; Android 14; {DEVICE_MODEL})",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    print(f"[DEBUG] SDK Mode - Package: {pkg}, Event: {event_name}, Revenue: {revenue}")
    
    try:
        if proxy:
            r = requests.post(url, json=payload, headers=headers, timeout=30, proxies=proxy)
        else:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"[DEBUG] Status: {r.status_code}, Response: {r.text[:100]}")
        return r.status_code, r.text
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        return 500, str(e)
def send_adj(app_token: str, event_token: str, gps_adid: str, proxy: Dict = None) -> Tuple[int, str]:
    """إرسال حدث إلى Adjust S2S API - صيغة GET (تحسب 100%)"""
    import requests
    import time
    
    # 🔥 استخدام GET كما في الرابط اللي أرسلته
    url = "https://s2s.adjust.com/event"
    
    # بناء المعاملات (params) بنفس صيغة الرابط
    params = {
        "app_token": app_token,
        "event_token": event_token,
        "gps_adid": gps_adid,
        "s2s": "1"  # 🔥 هذا مهم للاحتساب
    }
    
    # إضافة timestamp اختياري (لزيادة الواقعية)
    params["created_at"] = int(time.time())
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    print(f"[DEBUG] Adjust Request URL: {url}")
    print(f"[DEBUG] Adjust Params: {params}")
    
    try:
        if proxy:
            r = requests.get(url, params=params, headers=headers, timeout=30, proxies=proxy)
        else:
            r = requests.get(url, params=params, headers=headers, timeout=30)
        
        print(f"[DEBUG] Adjust Response: {r.status_code} - {r.text[:200]}")
        
        if r.status_code == 200:
            return 200, r.text
        return r.status_code, r.text
        
    except Exception as e:
        print(f"[DEBUG] Adjust Exception: {e}")
        return 500, str(e)
def send_singular(event_name, aifa, uid, package, app_key, level=None, proxy=None, platform="android", idfa=None, idfv=None):
    import requests
    import json
    import time
    
    url = "https://s2s.singular.net/api/v1/evt"
    current_ts = int(time.time() * 1000)
    
    # 🔥 استخدام aifa مباشرة (لأننا فرضنا Android)
    advertising_id = aifa
    
    print(f"[DEBUG] send_singular - Using AIFA: {advertising_id}")
    print(f"[DEBUG] send_singular - Package: {package}, App Key: {app_key}, Event: {event_name}")
    
    payload = {
        "a": app_key,
        "p": package,
        "i": advertising_id,
        "e": event_name,
        "t": current_ts,
    }
    
    if uid:
        payload["cu"] = uid
    
    if level:
        payload["lvl"] = level
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    print(f"[DEBUG] Singular Payload: {json.dumps(payload, indent=2)}")
    
    try:
        if proxy:
            r = requests.post(url, json=payload, headers=headers, timeout=30, proxies=proxy)
        else:
            r = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"[DEBUG] Singular Response: {r.status_code} - {r.text[:200]}")
        
        if r.status_code == 200:
            return 200, r.text
        return r.status_code, r.text
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        return 500, str(e)
# ==================================================================================
#                             مزرعة الجمبرة (الكاملة)
# ==================================================================================

async def jumper_farm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🌾 مزرعة جديدة", callback_data="farm_new")],
        [InlineKeyboardButton("📋 مزارعي", callback_data="farm_list")],
        [InlineKeyboardButton("⚙️ وضع خاص", callback_data="farm_special")],
        [InlineKeyboardButton("⏹️ إيقاف مزرعة", callback_data="farm_stop")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text(
        "🌾 *مزرعة الجمبرة المطورة* 🌾\n\n"
        "✨ *الأوضاع المتاحة:*\n"
        "• 🛡️ وضع آمن: 1 لفل/يوم\n"
        "• ⚡ وضع عادي: 3 لفل/يوم\n"
        "• 🚀 وضع سريع: 5 لفل/يوم\n"
        "• 🎮 وضع خاص: تحكم كامل بالوقت لكل لفل\n\n"
        "⚠️ *يجب إعداد بروكسي أولاً*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "FARM_MAIN"

# ==================================================================================
#                             المزرعة العادية
# ==================================================================================

async def farm_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    proxy = get_proxy_for_user(uid)
    if not proxy:
        await query.edit_message_text(
            "❌ *لا يمكن إنشاء مزرعة بدون بروكسي!*\n\nيرجى إضافة بروكسي أولاً",
            parse_mode="Markdown"
        )
        await asyncio.sleep(2)
        await jumper_farm_menu(update, context)
        return -1
    
    context.user_data["farm_step"] = "platform"
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="farm_platform_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="farm_platform_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="farm_platform_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]
    ]
    await query.edit_message_text("🌾 *اختر المنصة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_PLATFORM"

async def farm_platform_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["farm_platform"] = "af"
    games = get_all_games_af()
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"farm_game_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_new")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_GAME"

async def farm_platform_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["farm_platform"] = "adj"
    games = get_all_games_adj()
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"farm_game_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_new")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_GAME"

async def farm_platform_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["farm_platform"] = "singular"
    games = get_all_games_singular()
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"farm_game_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_new")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_GAME"

async def farm_game_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    platform = parts[2]
    game_id = int(parts[3])
    context.user_data["farm_game_id"] = game_id
    
    if platform == "af":
        game = c_main.execute("SELECT display_name FROM games_af WHERE id = ?", (game_id,)).fetchone()
        context.user_data["farm_game_name"] = game[0]
        user_platform = get_user_platform(query.from_user.id)
        if user_platform == "ios":
            await query.edit_message_text("🍎 *iOS - AppsFlyer*\n\n📱 *أدخل IDFA:*\nمثال: `12345678-1234-1234-1234-123456789012`", parse_mode="Markdown")
            return "FARM_IDFA_AF"
        else:
            await query.edit_message_text("🤖 *Android - AppsFlyer*\n\n📱 *أدخل GAID:*\nمثال: `8de8604d-1318-4fd0-907c-402ea9de2529`", parse_mode="Markdown")
            return "FARM_GAID"
    elif platform == "adj":
        game = c_main.execute("SELECT display_name FROM games_adj WHERE id = ?", (game_id,)).fetchone()
        context.user_data["farm_game_name"] = game[0]
        user_platform = get_user_platform(query.from_user.id)
        if user_platform == "ios":
            await query.edit_message_text("🍎 *iOS - Adjust*\n\n📱 *أدخل IDFA:*\nمثال: `12345678-1234-1234-1234-123456789012`\n\n⚠️ *سيتم استخدامه كـ GPS ADID*", parse_mode="Markdown")
            return "FARM_GPS_ADID"
        else:
            await query.edit_message_text("🤖 *Android - Adjust*\n\n📱 *أدخل GPS ADID:*\nمثال: `8de8604d-1318-4fd0-907c-402ea9de2529`", parse_mode="Markdown")
            return "FARM_GPS_ADID"
    else:
        game = c_main.execute("SELECT display_name FROM games_singular WHERE id = ?", (game_id,)).fetchone()
        context.user_data["farm_game_name"] = game[0]
        user_platform = get_user_platform(query.from_user.id)
        if user_platform == "ios":
            await query.edit_message_text("🍎 *iOS - Singular*\n\n📱 *أدخل IDFA:*\nمثال: `12345678-1234-1234-1234-123456789012`", parse_mode="Markdown")
            return "FARM_IDFA_SINGULAR"
        else:
            await query.edit_message_text("🤖 *Android - Singular*\n\n📱 *أدخل AIFA (GAID):*\nمثال: `8de8604d-1318-4fd0-907c-402ea9de2529`", parse_mode="Markdown")
            return "FARM_AIFA"

async def farm_idfa_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfa"] = update.message.text.strip()
    await update.message.reply_text("🍎 *أدخل IDFV:*\nمثال: `12345678-1234-1234-1234-123456789012`", parse_mode="Markdown")
    return "FARM_IDFV_AF"

async def farm_idfv_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfv"] = update.message.text.strip()
    await update.message.reply_text("📱 *أدخل AF ID (AppsFlyer ID):*\nمثال: `1777078015955-4325801374339884483`", parse_mode="Markdown")
    return "FARM_AF_UID"

async def farm_af_uid_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_af_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_START_LEVEL"

async def farm_gaid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_gaid"] = update.message.text.strip()
    await update.message.reply_text("📱 *أدخل AF UID (AppsFlyer ID):*\nمثال: `1777078015955-4325801374339884483`", parse_mode="Markdown")
    return "FARM_AF_UID"

async def farm_af_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_af_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_START_LEVEL"

async def farm_gps_adid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_gps"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_START_LEVEL"

async def farm_idfa_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfa"] = update.message.text.strip()
    await update.message.reply_text("🍎 *أدخل IDFV:*\nمثال: `12345678-1234-1234-1234-123456789012`", parse_mode="Markdown")
    return "FARM_IDFV_SINGULAR"

async def farm_idfv_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfv"] = update.message.text.strip()
    await update.message.reply_text("🆔 *أدخل Custom User ID:*\nمثال: `your_user_id_123`", parse_mode="Markdown")
    return "FARM_SINGULAR_UID"

async def farm_singular_uid_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_singular_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_START_LEVEL"

async def farm_aifa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_aifa"] = update.message.text.strip()
    await update.message.reply_text("🆔 *أدخل Custom User ID:*\nمثال: `your_user_id_123`", parse_mode="Markdown")
    return "FARM_SINGULAR_UID"

async def farm_singular_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_singular_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_START_LEVEL"

async def farm_start_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sl = int(update.message.text.strip())
        context.user_data["farm_start"] = sl
        await update.message.reply_text(f"🔢 *مستوى النهاية:* (من {sl} إلى ?)\nمثال: `30`", parse_mode="Markdown")
        return "FARM_END_LEVEL"
    except:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_START_LEVEL"

async def farm_end_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        el = int(update.message.text.strip())
        sl = context.user_data["farm_start"]
        if el <= sl:
            await update.message.reply_text("❌ *يجب أن يكون أكبر من مستوى البداية*", parse_mode="Markdown")
            return "FARM_END_LEVEL"
        context.user_data["farm_end"] = el
        total = el - sl + 1
        await update.message.reply_text(f"📅 *عدد الأيام:* (إجمالي {total} مستوى)\nمثال: `{total}`", parse_mode="Markdown")
        return "FARM_TOTAL_DAYS"
    except:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_END_LEVEL"

async def farm_total_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        if days <= 0:
            await update.message.reply_text("❌ *عدد الأيام يجب أن يكون أكبر من 0*", parse_mode="Markdown")
            return "FARM_TOTAL_DAYS"
        context.user_data["farm_days"] = days
        kb = [
            [InlineKeyboardButton("🛡️ وضع آمن (1 لفل/يوم)", callback_data="farm_mode_safe")],
            [InlineKeyboardButton("⚡ وضع عادي (3 لفل/يوم)", callback_data="farm_mode_normal")],
            [InlineKeyboardButton("🚀 وضع سريع (5 لفل/يوم)", callback_data="farm_mode_fast")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="farm_new")]
        ]
        total_levels = context.user_data["farm_end"] - context.user_data["farm_start"] + 1
        await update.message.reply_text(
            f"⚙️ *اختر وضع التشغيل*\n\n"
            f"📊 المستويات: {context.user_data['farm_start']} → {context.user_data['farm_end']}\n"
            f"📅 عدد الأيام: {days}\n"
            f"📈 المتوسط اليومي: {total_levels/days:.1f} لفل/يوم",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return "FARM_MODE"
    except:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_TOTAL_DAYS"

async def farm_mode_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.replace("farm_mode_", "")
    mode_names = {"safe": "🛡️ آمن", "normal": "⚡ عادي", "fast": "🚀 سريع"}
    context.user_data["farm_mode"] = mode
    
    kb = [
        [InlineKeyboardButton("✅ تأكيد وبدء الزراعة", callback_data="farm_confirm")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="farm_new")]
    ]
    
    total_levels = context.user_data["farm_end"] - context.user_data["farm_start"] + 1
    await query.edit_message_text(
        f"📋 *ملخص المزرعة*\n\n"
        f"╭━━━━━━━━━━━━━━━━━━━━━╮\n"
        f"┃ 🎮 المنصة: {context.user_data['farm_platform']}\n"
        f"┃ 🎲 اللعبة: {context.user_data['farm_game_name']}\n"
        f"┃ 🎯 المستويات: {context.user_data['farm_start']} → {context.user_data['farm_end']}\n"
        f"┃ 📅 عدد الأيام: {context.user_data['farm_days']}\n"
        f"┃ ⚙️ الوضع: {mode_names[mode]}\n"
        f"┃ 🎯 إجمالي الضربات: {total_levels}\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"✨ *هل أنت متأكد من بدء المزرعة؟*\n"
        f"⚠️ *سيتم استخدام البروكسي الخاص بك*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "FARM_CONFIRM"

async def farm_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    task_name = f"Farm_{int(time.time())}_{uid}"
    
    c_main.execute("""INSERT INTO farm_tasks 
    (user_id, task_name, platform, game_id, game_name, start_level, end_level, total_days, mode, current_day, current_level, status, created_date, aifa, gaid, uid, af_uid, gps_adid, idfa, idfv)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (uid, task_name, context.user_data["farm_platform"], context.user_data["farm_game_id"], context.user_data["farm_game_name"],
     context.user_data["farm_start"], context.user_data["farm_end"], context.user_data["farm_days"], context.user_data["farm_mode"],
     1, context.user_data["farm_start"], "running", datetime.now().isoformat(),
     context.user_data.get("farm_aifa", ""), context.user_data.get("farm_gaid", ""), context.user_data.get("farm_singular_uid", ""),
     context.user_data.get("farm_af_uid", ""), context.user_data.get("farm_gps", ""), context.user_data.get("farm_idfa", ""), context.user_data.get("farm_idfv", "")))
    conn_main.commit()
    
    total_levels = context.user_data["farm_end"] - context.user_data["farm_start"] + 1
    task_id_result = c_main.execute("SELECT id FROM farm_tasks WHERE task_name = ?", (task_name,)).fetchone()
    if task_id_result:
        await send_farm_notification(context, uid, task_id_result[0], 
                                     context.user_data["farm_start"], total_levels - 1, total_levels, context.user_data["farm_game_name"])
    
    await query.edit_message_text(
        f"🌾 *تم إنشاء المزرعة بنجاح!*\n\n"
        f"🆔 معرف المهمة: `{task_name}`\n"
        f"📅 ستبدأ الزراعة خلال 24 ساعة\n\n"
        f"✨ استخدم 📋 المزارع النشطة للمتابعة",
        parse_mode="Markdown"
    )
    
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def farm_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    tasks = c_main.execute("SELECT id, task_name FROM farm_tasks WHERE user_id = ? AND status = 'running'", (uid,)).fetchall()
    
    if not tasks:
        await query.edit_message_text("📋 *لا توجد مزارع نشطة للإيقاف*", parse_mode="Markdown")
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]]
        await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
        return -1
    
    kb = [[InlineKeyboardButton(f"⏹️ {t[1]}", callback_data=f"farm_stop_task_{t[0]}")] for t in tasks]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")])
    
    await query.edit_message_text("⏹️ *اختر المزرعة لإيقافها*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_STOP_SELECT"

async def farm_stop_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("farm_stop_task_", ""))
    user_id = query.from_user.id
    
    c_main.execute("UPDATE farm_tasks SET status = 'stopped' WHERE id = ? AND user_id = ?", (task_id, user_id))
    conn_main.commit()
    
    await query.edit_message_text("✅ *تم إيقاف المزرعة بنجاح!*", parse_mode="Markdown")
    
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def farm_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    tasks = c_main.execute("SELECT id, task_name, platform, game_name, start_level, end_level, current_level, status, mode FROM farm_tasks WHERE user_id = ? AND status='running' ORDER BY created_date DESC", (uid,)).fetchall()
    if not tasks:
        await query.edit_message_text("📋 *لا توجد مزارع نشطة*", parse_mode="Markdown")
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]]
        await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
        return -1
    
    txt = "📋 *مزارعك النشطة*\n\n"
    for t in tasks:
        mode_name = {"safe": "🛡️ آمن", "normal": "⚡ عادي", "fast": "🚀 سريع", "special": "🎮 خاص"}.get(t[8] if len(t) > 8 else "normal", t[8] if len(t) > 8 else "normal")
        txt += f"• *{t[1]}*\n┣ 🎮 {t[3]}\n┣ 🎯 {t[4]} → {t[5]} (حالياً {t[6]})\n┣ 📊 الوضع: {mode_name}\n┣ 📌 الحالة: {t[7]}\n┗ 🆔 `{t[0]}`\n\n"
    
    kb = [
        [InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]
    ]
    await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return -1

# ==================================================================================
#                           دوال البوت الرئيسية
# ==================================================================================
# ==================================================================================
#                           دوال البوت الرئيسية
# ==================================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    name = update.effective_user.first_name or ""
    
    c_main.execute("INSERT OR IGNORE INTO users (user_id, username, name, created_at) VALUES (?, ?, ?, ?)",
                   (uid, uname, name, datetime.now().isoformat()))
    c_main.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?, ?)", (uid, "android"))
    conn_main.commit()
    
    if not is_allowed(uid):
        await update.message.reply_text(
            f"🚫 *غير مسموح*\n\nأنت غير مسجل في النظام.\nيرجى التواصل مع المدير.\n\n📞 {SUPPORT_USER} / ",
            parse_mode="Markdown"
        )
        return
    
    banned = c_main.execute("SELECT banned FROM users WHERE user_id = ?", (uid,)).fetchone()
    if banned and banned[0] == 1:
        await update.message.reply_text(f"🚫 *أنت محظور*\n\nللتواصل مع الدعم: {SUPPORT_USER}", parse_mode="Markdown")
        return
    
    current_platform = get_user_platform(uid)
    platform_emoji = "🤖" if current_platform == "android" else "🍎"
    
    kb = []
    if is_admin(uid):
        kb.append([InlineKeyboardButton("👑 لوحة التحكم", callback_data="admin_panel")])
    kb.append([InlineKeyboardButton("📱 AppsFlyer", callback_data="af")])
    kb.append([InlineKeyboardButton("📊 Adjust", callback_data="adj")])
    kb.append([InlineKeyboardButton("🌟 Singular", callback_data="singular")])
    kb.append([InlineKeyboardButton("🌾 مزرعة الجمبرة", callback_data="jumper_farm")])
    kb.append([InlineKeyboardButton("⏰ جدولة عمليات", callback_data="sched_menu")])
    kb.append([InlineKeyboardButton("🔧 إعدادات البروكسي", callback_data="proxy_settings")])
    kb.append([InlineKeyboardButton(f"{platform_emoji} نظام التشغيل", callback_data="select_platform")])
    
    await update.message.reply_text(
        f"⚡ *SYNC Jumper Bot* ⚡\n\n"
        f"╭━━━━━━━━━━━━━━━╮\n"
        f"┃ 📱 AppsFlyer\n┃ 📊 Adjust\n┃ 🌟 Singular\n┃ 🌾 مزرعة الجمبرة\n┃ 🔧 بروكسي\n┃ {platform_emoji} النظام: {current_platform.upper()}\n"
        f"╰━━━━━━━━━━━━━━━╯\n\n✨ *اختر الخدمة* ✨",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
async def clean_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنظيف شامل وبدء جديد"""
    uid = update.effective_user.id
    # تنظيف user_data بالكامل
    context.user_data.clear()
    # ضبط المنصة
    set_user_platform(uid, "android")
    await update.message.reply_text("✅ *تم التنظيف الشامل*\n\nالمنصة: Android\nالبيانات: تم مسحها\n\nاستخدم /start للبدء من جديد", parse_mode="Markdown")

# أضف في main():
    app.add_handler(CommandHandler("clean", clean_start))

# ==================================================================================
#                         دوال المدير لإضافة لعبة (AppsFlyer)
# ==================================================================================

async def admin_add_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="add_game_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="add_game_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="add_game_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("🎮 *اختر نوع اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_GAME_TYPE"

async def add_game_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "af"
    await query.edit_message_text("📱 *أدخل اسم اللعبة (name)*\nمثال: `my_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "adj"
    await query.edit_message_text("📊 *أدخل اسم اللعبة (name)*\nمثال: `my_adj_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "singular"
    await query.edit_message_text("🌟 *أدخل اسم اللعبة (name)*\nمثال: `my_singular_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_name"] = update.message.text.strip()
    await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
    return "ADD_GAME_DISPLAY"

async def add_game_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_display"] = update.message.text.strip()
    await update.message.reply_text("📦 *أدخل Package Name*", parse_mode="Markdown")
    return "ADD_GAME_PACKAGE"

async def add_game_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_package"] = update.message.text.strip()
    gtype = context.user_data["game_type"]
    if gtype == "af":
        await update.message.reply_text("🔑 *أدخل Dev Key*", parse_mode="Markdown")
        return "ADD_GAME_KEY"
    elif gtype == "adj":
        await update.message.reply_text("🔑 *أدخل App Token*", parse_mode="Markdown")
        return "ADD_GAME_KEY"
    else:
        await update.message.reply_text("🔑 *أدخل App Key*", parse_mode="Markdown")
        return "ADD_GAME_KEY"

async def add_game_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_key"] = update.message.text.strip()
    await update.message.reply_text("🎨 *أدخل الإيموجي* (اختياري)", parse_mode="Markdown")
    return "ADD_GAME_EMOJI"

async def add_game_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip() or "🎮"
    gtype = context.user_data["game_type"]
    name = context.user_data["game_name"]
    display = context.user_data["game_display"]
    pkg = context.user_data["game_package"]
    key = context.user_data["game_key"]
    
    if gtype == "af":
        c_main.execute("INSERT INTO games_af (name, display_name, package, dev_key, emoji) VALUES (?, ?, ?, ?, ?)",
                       (name, display, pkg, key, emoji))
    elif gtype == "adj":
        c_main.execute("INSERT INTO games_adj (name, display_name, app_token, emoji) VALUES (?, ?, ?, ?)",
                       (name, display, key, emoji))
    else:
        c_main.execute("INSERT INTO games_singular (name, display_name, package, app_key, emoji) VALUES (?, ?, ?, ?, ?)",
                       (name, display, pkg, key, emoji))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تم إضافة اللعبة*\n🎮 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1
async def singular_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    event_name = query.data.replace("singular_send_", "")
    
    ev = c_main.execute("SELECT display_name FROM events_singular WHERE game_id = ? AND event_name = ?", 
                        (context.user_data["sg_game_id"], event_name)).fetchone()
    display = ev[0] if ev else event_name
    
    # 🔥 جلب البيانات مع التحقق القوي
    pkg = context.user_data.get("sg_package")
    app_key = context.user_data.get("sg_app_key")
    aifa = context.user_data.get("sg_aifa", "")
    
    # 🔥 IMPORTANT: تجاهل platform من user_data وفرض Android
    platform = "android"
    uid = context.user_data.get("sg_uid", "")
    
    print(f"[DEBUG] Singular Send - Package: {pkg}")
    print(f"[DEBUG] Singular Send - App Key: {app_key}")
    print(f"[DEBUG] Singular Send - Platform: {platform} (FORCED)")
    print(f"[DEBUG] Singular Send - AIFA/GAID: {aifa}")
    print(f"[DEBUG] Singular Send - Event: {event_name}")
    
    # التحقق من البيانات
    if not pkg:
        await query.edit_message_text("❌ خطأ: Package Name غير موجود", parse_mode="Markdown")
        return -1
    
    if not app_key:
        await query.edit_message_text("❌ خطأ: App Key غير موجود", parse_mode="Markdown")
        return -1
    
    if not aifa:
        await query.edit_message_text("❌ خطأ: GAID/AIFA غير موجود. الرجاء إعادة اختيار اللعبة وإدخال GAID صحيح", parse_mode="Markdown")
        return -1
    
    proxy = get_proxy_for_user(query.from_user.id)
    
    await query.edit_message_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
    
    # 🔥 إرسال مع platform="android" فقط
    status, resp = send_singular(event_name, aifa, uid, pkg, app_key, None, proxy, "android")
    
    increment_user_requests(query.from_user.id)
    
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})\n`{resp[:100]}`"
    
    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"singular_resend_{context.user_data['sg_game_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")]
    ]
    
    await query.message.reply_text(
        f"{result}\n📝 *الحدث:* {display}\n🎮 *اللعبة:* {context.user_data['sg_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    current_platform = get_user_platform(uid)
    platform_emoji = "🤖" if current_platform == "android" else "🍎"
    
    kb = []
    if is_admin(uid):
        kb.append([InlineKeyboardButton("👑 لوحة التحكم", callback_data="admin_panel")])
    kb.append([InlineKeyboardButton("📱 AppsFlyer", callback_data="af")])
    kb.append([InlineKeyboardButton("📊 Adjust", callback_data="adj")])
    kb.append([InlineKeyboardButton("🌟 Singular", callback_data="singular")])
    kb.append([InlineKeyboardButton("🌾 مزرعة الجمبرة", callback_data="jumper_farm")])
    kb.append([InlineKeyboardButton("⏰ جدولة عمليات", callback_data="sched_menu")])
    kb.append([InlineKeyboardButton("🔧 إعدادات البروكسي", callback_data="proxy_settings")])
    kb.append([InlineKeyboardButton(f"{platform_emoji} نظام التشغيل", callback_data="select_platform")])
    
    await query.edit_message_text(
        f"🔥 *AK Jumper Bot* 🔥\n\n✨ *اختر الخدمة* ✨\n\n📱 النظام الحالي: {platform_emoji} {current_platform.upper()}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

# ==================================================================================
#                           نظام التشغيل
# ==================================================================================

async def select_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    current_platform = get_user_platform(user_id)
    platform_emoji = "🤖" if current_platform == "android" else "🍎"
    platform_name = "Android" if current_platform == "android" else "iOS"
    
    kb = [
        [InlineKeyboardButton("🤖 Android (GAID / AF UID)", callback_data="set_platform_android")],
        [InlineKeyboardButton("🍎 iOS (IDFA / IDFV)", callback_data="set_platform_ios")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    
    await query.edit_message_text(
        f"📱 *إعدادات نظام التشغيل*\n\n"
        f"╭━━━━━━━━━━━━━━━━━━━━━╮\n"
        f"┃ النظام الحالي: {platform_emoji} *{platform_name}*\n"
        f"┃\n"
        f"┃ 🤖 *Android*: يستخدم GAID و AF UID\n"
        f"┃\n"
        f"┃ 🍎 *iOS*: يستخدم IDFA و IDFV\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"✨ *اختر نظام التشغيل المناسب لجهازك*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def set_platform_android(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    set_user_platform(user_id, "android")
    await query.edit_message_text("✅ *تم التغيير إلى Android*", parse_mode="Markdown")
    await asyncio.sleep(1)
    await main_menu(update, context)
    return -1

async def set_platform_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    set_user_platform(user_id, "ios")
    await query.edit_message_text("✅ *تم التغيير إلى iOS*\n\n⚠️ سيتم طلب IDFA, IDFV, AF ID", parse_mode="Markdown")
    await asyncio.sleep(1)
    await main_menu(update, context)
    return -1

# ==================================================================================
#                               البروكسي
# ==================================================================================

# ==================================================================================
#                               البروكسي (المطور)
# ==================================================================================

async def proxy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    pinfo = get_proxy_info(uid)
    status = "❌ *لا يوجد بروكسي*" if not pinfo else f"✅ *البروكسي الحالي:*\n📡 النوع: `{pinfo[0]}`\n🌐 {pinfo[1]}:{pinfo[2]}"
    kb = [
        [InlineKeyboardButton("🔧 إضافة بروكسي", callback_data="proxy_add")],
        [InlineKeyboardButton("🗑️ حذف البروكسي", callback_data="proxy_del")],
        [InlineKeyboardButton("📡 اختبار البروكسي", callback_data="proxy_test")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text(
        f"🔧 *إعدادات البروكسي*\n\n{status}\n\n"
        f"✨ *اختر إجراء:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "PROXY_MAIN"

async def proxy_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار نوع البروكسي"""
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🔒 HTTP / HTTPS", callback_data="proxy_type_http")],
        [InlineKeyboardButton("🔓 SOCKS5", callback_data="proxy_type_socks5")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="proxy_settings")]
    ]
    await query.edit_message_text(
        "🔧 *إضافة بروكسي جديد*\n\n"
        "✨ *اختر نوع البروكسي:*\n\n"
        "• 🔒 HTTP/HTTPS: للبروكسيات العادية\n"
        "• 🔓 SOCKS5: للبروكسيات الآمنة",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "PROXY_TYPE"

async def proxy_type_http(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار HTTP"""
    query = update.callback_query
    await query.answer()
    context.user_data["proxy_type"] = "http"
    await query.edit_message_text(
        "🔒 *بروكسي HTTP/HTTPS*\n\n"
        "📝 *أدخل IP والمنفذ:*\n"
        "مثال: `192.168.1.100:8080`\n\n"
        "⚠️ *يمكنك إضافة اسم مستخدم وكلمة مرور بعد ذلك*",
        parse_mode="Markdown"
    )
    return "PROXY_IP_PORT"

async def proxy_type_socks5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار SOCKS5"""
    query = update.callback_query
    await query.answer()
    context.user_data["proxy_type"] = "socks5"
    await query.edit_message_text(
        "🔓 *بروكسي SOCKS5*\n\n"
        "📝 *أدخل IP والمنفذ:*\n"
        "مثال: `192.168.1.100:1080`\n\n"
        "⚠️ *يمكنك إضافة اسم مستخدم وكلمة مرور بعد ذلك*",
        parse_mode="Markdown"
    )
    return "PROXY_IP_PORT"

async def proxy_ip_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدخال IP والمنفذ"""
    ip_port = update.message.text.strip()
    try:
        if ":" not in ip_port:
            await update.message.reply_text("❌ *صيغة خاطئة*\nاستخدم: `ip:port`", parse_mode="Markdown")
            return "PROXY_IP_PORT"
        
        host, port = ip_port.split(":", 1)
        port = int(port)
        
        context.user_data["proxy_host"] = host
        context.user_data["proxy_port"] = port
        
        kb = [
            [InlineKeyboardButton("✅ لا، بدون مصادقة", callback_data="proxy_no_auth")],
            [InlineKeyboardButton("🔐 نعم، إضافة مصادقة", callback_data="proxy_need_auth")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="proxy_add")]
        ]
        await update.message.reply_text(
            f"✅ *تم تعيين:* `{host}:{port}`\n\n"
            f"🔐 *هل تحتاج المصادقة (Username/Password)؟*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return "PROXY_AUTH"
        
    except ValueError:
        await update.message.reply_text("❌ *المنفذ يجب أن يكون رقماً*", parse_mode="Markdown")
        return "PROXY_IP_PORT"
    except Exception as e:
        await update.message.reply_text(f"❌ *خطأ:* `{e}`", parse_mode="Markdown")
        return "PROXY_IP_PORT"

async def proxy_no_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدون مصادقة - حفظ البروكسي مباشرة"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["proxy_user"] = ""
    context.user_data["proxy_pass"] = ""
    
    uid = update.effective_user.id
    proxy_type = context.user_data.get("proxy_type", "http")
    host = context.user_data.get("proxy_host")
    port = context.user_data.get("proxy_port")
    
    await query.edit_message_text("📡 *جاري حفظ واختبار البروكسي...*", parse_mode="Markdown")
    
    # حفظ البروكسي في قاعدة البيانات
    save_proxy(uid, proxy_type, host, port, "", "")
    
    # بناء البروكسي للاختبار
    if proxy_type == "socks5":
        proxy_url = f"socks5://{host}:{port}"
        proxies = {"socks5": proxy_url, "http": proxy_url, "https": proxy_url}
    else:
        proxy_url = f"http://{host}:{port}"
        proxies = {"http": proxy_url, "https": proxy_url}
    
    # اختبار البروكسي
    try:
        test_url = 'https://api.ipify.org?format=json'
        response = requests.get(test_url, proxies=proxies, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            proxy_ip = data.get('ip', 'Unknown')
            
            await query.message.reply_text(
                f"✅ *تم حفظ البروكسي بنجاح!*\n\n"
                f"📡 *النوع:* `{proxy_type.upper()}`\n"
                f"🌐 *السيرفر:* `{host}:{port}`\n"
                f"🌍 *IP البروكسي:* `{proxy_ip}`\n\n"
                f"✨ *البروكسي يعمل وجاهز للاستخدام*",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(
                f"❌ *البروكسي لا يعمل*\n\n"
                f"📡 *النوع:* `{proxy_type.upper()}`\n"
                f"🌐 *السيرفر:* `{host}:{port}`\n\n"
                f"💡 *يرجى التحقق من البيانات أو تجربة بروكسي آخر*",
                parse_mode="Markdown"
            )
            delete_proxy(uid)
    except Exception:
        await query.message.reply_text(
            f"❌ *البروكسي لا يعمل*\n\n"
            f"📡 *النوع:* `{proxy_type.upper()}`\n"
            f"🌐 *السيرفر:* `{host}:{port}`\n\n"
            f"💡 *يرجى التحقق من البيانات أو تجربة بروكسي آخر*",
            parse_mode="Markdown"
        )
        delete_proxy(uid)
    
    # تنظيف البيانات المؤقتة
    for key in ['proxy_type', 'proxy_host', 'proxy_port', 'proxy_user', 'proxy_pass']:
        context.user_data.pop(key, None)
    
    kb = [[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="main")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def proxy_need_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مطلوب مصادقة"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔐 *إضافة المصادقة*\n\n"
        "📝 *أدخل اسم المستخدم (Username):*",
        parse_mode="Markdown"
    )
    return "PROXY_USERNAME"

async def proxy_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدخال اسم المستخدم"""
    context.user_data["proxy_user"] = update.message.text.strip()
    await update.message.reply_text(
        "🔑 *أدخل كلمة المرور (Password):*",
        parse_mode="Markdown"
    )
    return "PROXY_PASSWORD"

async def proxy_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدخال كلمة المرور وحفظ البروكسي"""
    user = context.user_data.get("proxy_user", "")
    pwd = update.message.text.strip()
    
    uid = update.effective_user.id
    proxy_type = context.user_data.get("proxy_type", "http")
    host = context.user_data.get("proxy_host")
    port = context.user_data.get("proxy_port")
    
    await update.message.reply_text("📡 *جاري حفظ واختبار البروكسي...*", parse_mode="Markdown")
    
    # حفظ البروكسي في قاعدة البيانات
    save_proxy(uid, proxy_type, host, port, user, pwd)
    
    # بناء البروكسي للاختبار
    if user and pwd:
        auth = f"{user}:{pwd}@"
    else:
        auth = ""
    
    if proxy_type == "socks5":
        proxy_url = f"socks5://{auth}{host}:{port}"
        proxies = {"socks5": proxy_url, "http": proxy_url, "https": proxy_url}
    else:
        proxy_url = f"http://{auth}{host}:{port}"
        proxies = {"http": proxy_url, "https": proxy_url}
    
    # اختبار البروكسي
    try:
        test_url = 'https://api.ipify.org?format=json'
        response = requests.get(test_url, proxies=proxies, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            proxy_ip = data.get('ip', 'Unknown')
            
            await update.message.reply_text(
                f"✅ *تم حفظ البروكسي بنجاح!*\n\n"
                f"📡 *النوع:* `{proxy_type.upper()}`\n"
                f"🌐 *السيرفر:* `{host}:{port}`\n"
                f"🌍 *IP البروكسي:* `{proxy_ip}`\n\n"
                f"✨ *البروكسي يعمل وجاهز للاستخدام*",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ *البروكسي لا يعمل*\n\n"
                f"📡 *النوع:* `{proxy_type.upper()}`\n"
                f"🌐 *السيرفر:* `{host}:{port}`\n\n"
                f"💡 *يرجى التحقق من البيانات أو تجربة بروكسي آخر*",
                parse_mode="Markdown"
            )
            delete_proxy(uid)
    except Exception:
        await update.message.reply_text(
            f"❌ *البروكسي لا يعمل*\n\n"
            f"📡 *النوع:* `{proxy_type.upper()}`\n"
            f"🌐 *السيرفر:* `{host}:{port}`\n\n"
            f"💡 *يرجى التحقق من البيانات أو تجربة بروكسي آخر*",
            parse_mode="Markdown"
        )
        delete_proxy(uid)
    
    # تنظيف البيانات المؤقتة
    for key in ['proxy_type', 'proxy_host', 'proxy_port', 'proxy_user', 'proxy_pass']:
        context.user_data.pop(key, None)
    
    kb = [[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="main")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

# ==================================================================================
#                           دوال المدير الأساسية
# ==================================================================================

# ==================================================================================
#                             دوال المدير الكاملة
# ==================================================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("👥 المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("➕ إضافة مستخدم", callback_data="admin_add_user")],
        [InlineKeyboardButton("🗑️ حذف مستخدم", callback_data="admin_remove_user")],
        [InlineKeyboardButton("🚫 حظر", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 إلغاء حظر", callback_data="admin_unban")],
        [InlineKeyboardButton("📋 المحظورين", callback_data="admin_banned_list")],
        [InlineKeyboardButton("📋 المسموح", callback_data="admin_allowed_list")],
        [InlineKeyboardButton("🎮 إضافة لعبة", callback_data="admin_add_game")],
        [InlineKeyboardButton("🗑️ حذف لعبة", callback_data="admin_delete_game")],
        [InlineKeyboardButton("🎯 إضافة حدث", callback_data="admin_add_event")],
        [InlineKeyboardButton("🗑️ حذف حدث", callback_data="admin_delete_event")],
        [InlineKeyboardButton("📢 بث", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text("👑 *لوحة تحكم المدير*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return -1

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tu = c_main.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    ta = c_main.execute("SELECT COUNT(*) FROM allowed_users").fetchone()[0]
    tb = c_main.execute("SELECT COUNT(*) FROM users WHERE banned=1").fetchone()[0]
    tr = c_main.execute("SELECT SUM(total_requests) FROM users").fetchone()[0] or 0
    tf = c_main.execute("SELECT COUNT(*) FROM farm_tasks WHERE status='running'").fetchone()[0]
    tg_af = c_main.execute("SELECT COUNT(*) FROM games_af").fetchone()[0]
    tg_sg = c_main.execute("SELECT COUNT(*) FROM games_singular").fetchone()[0]
    tg_adj = c_main.execute("SELECT COUNT(*) FROM games_adj").fetchone()[0]
    tp = c_main.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
    
    txt = f"""📊 *إحصائيات البوت*

╭━━━━━━━━━━━━━━━━━━━━━╮
┃ 👥 *المستخدمين*
┃ ┣ 📈 الإجمالي: {tu}
┃ ┣ ✅ المسموح: {ta}
┃ ┗ 🚫 المحظور: {tb}

┃ 🎮 *الألعاب*
┃ ┣ 📱 AppsFlyer: {tg_af}
┃ ┣ 🌟 Singular: {tg_sg}
┃ ┗ 📊 Adjust: {tg_adj}

┃ 🌾 *المزرعة*
┃ ┗ 🏃 مزارع نشطة: {tf}

┃ 🔧 *البروكسي*
┃ ┗ 🔒 عدد البروكسيات: {tp}

┃ 📊 *الطلبات*
┃ ┗ 🎯 إجمالي الطلبات: {tr}
╰━━━━━━━━━━━━━━━━━━━━━╯"""
    
    await query.edit_message_text(txt, parse_mode="Markdown")
    await asyncio.sleep(2)
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = c_main.execute("SELECT user_id, username, name, last_use, banned, allowed, total_requests FROM users LIMIT 50").fetchall()
    txt = "👥 *قائمة المستخدمين*\n\n"
    for u in users:
        ban = "🚫" if u[4] == 1 else "✅"
        allowed = "🔓" if u[5] == 1 else "🔒"
        last = u[3][:16] if u[3] else "لم يستخدم"
        txt += f"• `{u[0]}` {ban}{allowed} | @{u[1] or '-'} | {u[2] or '-'} | {last} | 📊{u[6] or 0}\n"
        if len(txt) > 3500:
            break
    await query.edit_message_text(txt[:4000], parse_mode="Markdown")
    await asyncio.sleep(3)
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_allowed_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = get_allowed_users()
    if not users:
        txt = "📋 *لا يوجد مستخدمين مسموح لهم*"
    else:
        txt = "📋 *المستخدمين المسموح لهم*\n\n"
        for u in users:
            txt += f"• `{u[0]}` | @{u[1] or '-'} | {u[2] or '-'}\n"
    await query.edit_message_text(txt[:4000], parse_mode="Markdown")
    await asyncio.sleep(2)
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = c_main.execute("SELECT user_id, username, name FROM users WHERE banned = 1").fetchall()
    if not users:
        txt = "📋 *لا يوجد مستخدمين محظورين*"
    else:
        txt = "🚫 *المستخدمين المحظورين*\n\n"
        for u in users:
            txt += f"• `{u[0]}` | @{u[1] or '-'} | {u[2] or '-'}\n"
    await query.edit_message_text(txt[:4000], parse_mode="Markdown")
    await asyncio.sleep(2)
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ *أدخل معرف المستخدم (ID)*\nمثال: `6075014046`", parse_mode="Markdown")
    return "ADMIN_ADD_USER"

async def admin_add_user_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ *معرف غير صالح*", parse_mode="Markdown")
        return -1
    user = c_main.execute("SELECT user_id, username, name FROM users WHERE user_id = ?", (uid,)).fetchone()
    if not user:
        await update.message.reply_text("❌ *المستخدم غير موجود*", parse_mode="Markdown")
        return -1
    add_allowed_user(uid, user[1] or "", user[2] or "", update.effective_user.id)
    c_main.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?, ?)", (uid, "android"))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تمت إضافة المستخدم* `{uid}`", parse_mode="Markdown")
    try:
        await context.bot.send_message(uid, "🎉 *تم تفعيل حسابك!*\nيمكنك الآن استخدام البوت", parse_mode="Markdown")
    except:
        pass
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🗑️ *أدخل معرف المستخدم (ID)*\nمثال: `6075014046`", parse_mode="Markdown")
    return "ADMIN_REMOVE_USER"

async def admin_remove_user_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ *معرف غير صالح*", parse_mode="Markdown")
        return -1
    remove_allowed_user(uid)
    c_main.execute("DELETE FROM user_platform WHERE user_id = ?", (uid,))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تم حذف المستخدم* `{uid}`", parse_mode="Markdown")
    try:
        await context.bot.send_message(uid, "🚫 *تم إلغاء تفعيل حسابك*", parse_mode="Markdown")
    except:
        pass
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🚫 *أدخل معرف المستخدم (ID)*\nمثال: `6075014046`", parse_mode="Markdown")
    return "ADMIN_BAN"

async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ *معرف غير صالح*", parse_mode="Markdown")
        return -1
    c_main.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (uid,))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تم حظر المستخدم* `{uid}`", parse_mode="Markdown")
    try:
        await context.bot.send_message(uid, "🚫 *لقد تم حظرك من استخدام البوت*", parse_mode="Markdown")
    except:
        pass
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔓 *أدخل معرف المستخدم (ID)*\nمثال: `6075014046`", parse_mode="Markdown")
    return "ADMIN_UNBAN"

async def admin_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ *معرف غير صالح*", parse_mode="Markdown")
        return -1
    c_main.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (uid,))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تم إلغاء حظر المستخدم* `{uid}`", parse_mode="Markdown")
    try:
        await context.bot.send_message(uid, "✅ *تم إلغاء حظرك. يمكنك استخدام البوت الآن*", parse_mode="Markdown")
    except:
        pass
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["broadcast_msg"] = None
    await query.edit_message_text("📢 *أدخل رسالتك*\n✨ يمكنك استخدام Markdown", parse_mode="Markdown")
    return "ADMIN_BROADCAST_MSG"

async def admin_get_broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    context.user_data["broadcast_msg"] = msg
    kb = [
        [InlineKeyboardButton("✅ نعم, أرسل", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ لا, إلغاء", callback_data="broadcast_cancel")]
    ]
    await update.message.reply_text(
        f"📢 *تأكيد الإرسال*\n\n📝 الرسالة:\n`{msg[:200]}`\n\n⚠️ *هل أنت متأكد؟*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "ADMIN_BROADCAST_CONFIRM"

async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "broadcast_cancel":
        await query.edit_message_text("❌ *تم إلغاء الإرسال*", parse_mode="Markdown")
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
        await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
        return -1
    msg = context.user_data.get("broadcast_msg", "")
    if not msg:
        await query.edit_message_text("❌ *لا توجد رسالة للإرسال*", parse_mode="Markdown")
        return -1
    await query.edit_message_text("📢 *جاري الإرسال...*", parse_mode="Markdown")
    users = c_main.execute("SELECT user_id FROM users WHERE banned = 0").fetchall()
    sent = 0
    failed = 0
    for user in users:
        try:
            await context.bot.send_message(user[0], msg, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    await query.message.reply_text(f"✅ *تم الإرسال*\n\n📨 تم: {sent}\n❌ فشل: {failed}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

# ==================================================================================
#                         دوال المدير لإضافة لعبة وحدث
# ==================================================================================

async def admin_add_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="add_game_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="add_game_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="add_game_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("🎮 *اختر نوع اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_GAME_TYPE"

async def add_game_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "af"
    await query.edit_message_text("📱 *أدخل اسم اللعبة (name)*\nمثال: `my_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "adj"
    await query.edit_message_text("📊 *أدخل اسم اللعبة (name)*\nمثال: `my_adj_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "singular"
    await query.edit_message_text("🌟 *أدخل اسم اللعبة (name)*\nمثال: `my_singular_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_name"] = update.message.text.strip()
    await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
    return "ADD_GAME_DISPLAY"

async def add_game_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_display"] = update.message.text.strip()
    await update.message.reply_text("📦 *أدخل Package Name*", parse_mode="Markdown")
    return "ADD_GAME_PACKAGE"

async def add_game_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_package"] = update.message.text.strip()
    gtype = context.user_data["game_type"]
    if gtype == "af":
        await update.message.reply_text("🔑 *أدخل Dev Key*", parse_mode="Markdown")
        return "ADD_GAME_KEY"
    elif gtype == "adj":
        await update.message.reply_text("🔑 *أدخل App Token*", parse_mode="Markdown")
        return "ADD_GAME_KEY"
    else:
        await update.message.reply_text("🔑 *أدخل App Key*", parse_mode="Markdown")
        return "ADD_GAME_KEY"

async def add_game_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_key"] = update.message.text.strip()
    await update.message.reply_text("🎨 *أدخل الإيموجي* (اختياري)", parse_mode="Markdown")
    return "ADD_GAME_EMOJI"

async def add_game_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip() or "🎮"
    gtype = context.user_data["game_type"]
    name = context.user_data["game_name"]
    display = context.user_data["game_display"]
    pkg = context.user_data["game_package"]
    key = context.user_data["game_key"]
    
    if gtype == "af":
        c_main.execute("INSERT INTO games_af (name, display_name, package, dev_key, emoji) VALUES (?, ?, ?, ?, ?)",
                       (name, display, pkg, key, emoji))
    elif gtype == "adj":
        c_main.execute("INSERT INTO games_adj (name, display_name, app_token, emoji) VALUES (?, ?, ?, ?)",
                       (name, display, key, emoji))
    else:
        c_main.execute("INSERT INTO games_singular (name, display_name, package, app_key, emoji) VALUES (?, ?, ?, ?, ?)",
                       (name, display, pkg, key, emoji))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تم إضافة اللعبة*\n🎮 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_delete_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="del_game_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="del_game_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="del_game_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("🗑️ *اختر نوع اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_TYPE"

async def del_game_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"del_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_game")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_SELECT"

async def del_game_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"del_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_game")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_SELECT"

async def del_game_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"del_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_game")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_SELECT"

async def del_game_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    gtype = parts[1]
    game_id = int(parts[2])
    
    if gtype == "af":
        c_main.execute("DELETE FROM events_af WHERE game_id = ?", (game_id,))
        c_main.execute("DELETE FROM games_af WHERE id = ?", (game_id,))
    elif gtype == "adj":
        c_main.execute("DELETE FROM events_adj WHERE game_id = ?", (game_id,))
        c_main.execute("DELETE FROM games_adj WHERE id = ?", (game_id,))
    else:
        c_main.execute("DELETE FROM events_singular WHERE game_id = ?", (game_id,))
        c_main.execute("DELETE FROM games_singular WHERE id = ?", (game_id,))
    conn_main.commit()
    await query.edit_message_text("✅ *تم حذف اللعبة*", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="add_event_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="add_event_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="add_event_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("🎯 *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_TYPE"

async def add_event_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"ev_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_add_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_GAME"

async def add_event_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"ev_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_add_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_GAME"

async def add_event_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"ev_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_add_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_GAME"

async def add_event_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    try:
        context.user_data["event_game_type"] = parts[1]
        context.user_data["event_game_id"] = int(parts[2])
    except (IndexError, ValueError):
        await query.edit_message_text("❌ خطأ في بيانات اللعبة", parse_mode="Markdown")
        return -1
    await query.edit_message_text("📝 *أدخل اسم الحدث (event_name)*", parse_mode="Markdown")
    return "ADD_EVENT_NAME"

async def add_event_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["event_name"] = update.message.text.strip()
    gtype = context.user_data["event_game_type"]
    if gtype == "adj":
        await update.message.reply_text("🔑 *أدخل Event Token*", parse_mode="Markdown")
        return "ADD_EVENT_TOKEN"
    else:
        await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
        return "ADD_EVENT_DISPLAY"

async def add_event_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    display = update.message.text.strip()
    gtype = context.user_data["event_game_type"]
    game_id = context.user_data["event_game_id"]
    event_name = context.user_data["event_name"]
    
    if gtype == "af":
        c_main.execute("INSERT INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)",
                       (game_id, event_name, display, "custom", 0))
    else:
        c_main.execute("INSERT INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)",
                       (game_id, event_name, display, "custom"))
    conn_main.commit()
    cache_clear(f"af_events_{game_id}")
    cache_clear(f"singular_events_{game_id}")
    await update.message.reply_text(f"✅ *تم إضافة الحدث*\n📝 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def add_event_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    context.user_data["event_token"] = token
    await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
    return "ADD_EVENT_DISPLAY_ADJ"

async def add_event_display_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    display = update.message.text.strip()
    game_id = context.user_data["event_game_id"]
    event_name = context.user_data["event_name"]
    token = context.user_data["event_token"]
    
    c_main.execute("INSERT INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                   (game_id, event_name, token, display, 0))
    conn_main.commit()
    cache_clear(f"adj_events_{game_id}")
    await update.message.reply_text(f"✅ *تم إضافة الحدث*\n📝 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="del_event_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="del_event_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="del_event_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]
    ]
    await query.edit_message_text("🗑️ *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_TYPE"

async def del_event_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"dev_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_GAME"

async def del_event_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"dev_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_GAME"

async def del_event_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"dev_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_GAME"

async def del_event_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    gtype = parts[1]
    try:
        game_id = int(parts[2])
    except ValueError:
        await query.edit_message_text("❌ خطأ في معرف اللعبة", parse_mode="Markdown")
        return -1
    
    if gtype == "af":
        events = c_main.execute("SELECT id, display_name FROM events_af WHERE game_id = ?", (game_id,)).fetchall()
    elif gtype == "adj":
        events = c_main.execute("SELECT id, display_name FROM events_adj WHERE game_id = ?", (game_id,)).fetchall()
    else:
        events = c_main.execute("SELECT id, display_name FROM events_singular WHERE game_id = ?", (game_id,)).fetchall()
    
    if not events:
        await query.edit_message_text("❌ *لا توجد أحداث*", parse_mode="Markdown")
        return -1
    
    kb = [[InlineKeyboardButton(ev[1], callback_data=f"delev_{gtype}_{ev[0]}")] for ev in events]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎯 *اختر الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_SELECT"

async def del_event_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    gtype = parts[1]
    try:
        event_id = int(parts[2])
    except ValueError:
        await query.edit_message_text("❌ خطأ في معرف الحدث", parse_mode="Markdown")
        return -1
    
    if gtype == "af":
        c_main.execute("DELETE FROM events_af WHERE id = ?", (event_id,))
    elif gtype == "adj":
        c_main.execute("DELETE FROM events_adj WHERE id = ?", (event_id,))
    else:
        c_main.execute("DELETE FROM events_singular WHERE id = ?", (event_id,))
    conn_main.commit()
    cache_clear()
    await query.edit_message_text("✅ *تم حذف الحدث*", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

# ==================================================================================
#                               AppsFlyer
# ==================================================================================
async def af_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = [
        [InlineKeyboardButton("🎮 عرض الألعاب", callback_data="af_show_games")],
        [InlineKeyboardButton("🔍 بحث", callback_data="af_search_game")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text("📱 *AppsFlyer*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "AF_MAIN"

async def af_show_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"afgame_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="af_menu")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "AF_GAME"

async def af_search_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 *أدخل اسم اللعبة*", parse_mode="Markdown")
    return "AF_SEARCH"

async def af_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    games = c_main.execute("SELECT id, display_name, emoji FROM games_af WHERE display_name LIKE ?", (f"%{text}%",)).fetchall()
    if not games:
        await update.message.reply_text("❌ *لا يوجد*", parse_mode="Markdown")
        return "AF_SEARCH"
    kb = [[InlineKeyboardButton(f"{g[2]} {g[1]}", callback_data=f"afgame_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="af_menu")])
    await update.message.reply_text("✅ *نتائج البحث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "AF_GAME"

async def af_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 1. استخراج معرف اللعبة من البيانات
    gid = int(query.data.replace("afgame_", ""))
    
    # 2. جلب بيانات اللعبة من قاعدة البيانات
    game = c_main.execute("SELECT id, name, display_name, package, dev_key, emoji FROM games_af WHERE id = ?", (gid,)).fetchone()
    
    if not game:
        await query.edit_message_text("❌ اللعبة غير موجودة", parse_mode="Markdown")
        return -1
    
    # 3. 🔥 **الجزء المهم: مسح أي بيانات قديمة وحفظ بيانات اللعبة الجديدة**
    # قم بمسح أي مفاتيح قديمة متعلقة بـ AppsFlyer
    keys_to_remove = ['af_pkg', 'af_dev_key', 'af_game_id', 'af_game_name', 'af_gaid', 'af_uid', 'af_idfa', 'af_idfv']
    for key in keys_to_remove:
        if key in context.user_data:
            del context.user_data[key]
    
    # حفظ بيانات اللعبة الجديدة
    context.user_data["af_game_id"] = game[0]          # معرف اللعبة
    context.user_data["af_game_name"] = game[2]        # الاسم الظاهر
    context.user_data["af_pkg"] = game[3]              # 🔥 package name (الأهم)
    context.user_data["af_dev_key"] = game[4]          # 🔥 dev key (الأهم)
    
    # طباعة للتأكد (يمكنك إزالتها بعد التأكد من عمل البوت)
    print(f"✅ [DEBUG] تم اختيار لعبة جديدة:")
    print(f"   - الاسم: {game[2]}")
    print(f"   - Package: {game[3]}")
    print(f"   - Dev Key: {game[4][:15]}...")
    
    # 4. معرفة نظام تشغيل المستخدم
    platform = get_user_platform(query.from_user.id)
    context.user_data["af_platform"] = platform
    
    print(f"[DEBUG] منصة المستخدم: {platform}")
    
    # 5. طلب البيانات المطلوبة حسب نظام التشغيل
    if platform == "ios":
        await query.edit_message_text(
            f"{game[5]} *{game[2]}*\n\n🍎 *نظام iOS*\n📱 *أدخل IDFA:*",
            parse_mode="Markdown"
        )
        return "AF_IDFA"
    else:
        await query.edit_message_text(
            f"{game[5]} *{game[2]}*\n\n🤖 *نظام Android*\n📱 *أدخل GAID:*",
            parse_mode="Markdown"
        )
        return "AF_GAID"

# ========== جمع بيانات iOS ==========
async def af_idfa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["af_idfa"] = update.message.text.strip()
    await update.message.reply_text("🍎 *أدخل IDFV:*\nمثال: `12345678-1234-1234-1234-123456789012`\n\n⚠️ *مطلوب لـ iOS (IDFV)*", parse_mode="Markdown")
    return "AF_IDFV"

async def af_idfv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["af_idfv"] = update.message.text.strip()
    await update.message.reply_text("📱 *أدخل AF ID (AppsFlyer ID):*\nمثال: `1777078015955-4325801374339884483`\n\n⚠️ *مطلوب لـ iOS (AF UID)*", parse_mode="Markdown")
    return "AF_UID"

async def af_uid_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["af_uid"] = update.message.text.strip()
    context.user_data["af_platform"] = "ios"
    
    kb = [
        [InlineKeyboardButton("⭐ Level / إنجاز", callback_data="af_level")],
        [InlineKeyboardButton("💰 Purchase / شراء", callback_data="af_purchase")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await update.message.reply_text("🎯 *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "AF_TYPE"

# ========== جمع بيانات Android ==========
async def af_gaid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال GAID للأندرويد - فرض Android"""
    context.user_data["af_gaid"] = update.message.text.strip()
    context.user_data["af_platform"] = "android"  # فرض Android بقوة
    print(f"[DEBUG] FORCED platform to: {context.user_data['af_platform']}")
    await update.message.reply_text("📱 *أدخل AF UID (AppsFlyer Unique ID):*\nمثال: `1777078015955-4325801374339884483`", parse_mode="Markdown")
    return "AF_UID"

async def af_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال AF UID للأندرويد"""
    context.user_data["af_uid"] = update.message.text.strip()
    context.user_data["af_platform"] = "android"  # فرض Android مرة أخرى
    print(f"[DEBUG] FINAL platform: {context.user_data['af_platform']}")
    
    kb = [
        [InlineKeyboardButton("⭐ Level / إنجاز", callback_data="af_level")],
        [InlineKeyboardButton("💰 Purchase / شراء", callback_data="af_purchase")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await update.message.reply_text("🎯 *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "AF_TYPE"

async def af_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_id = context.user_data["af_game_id"]
    
    events = get_af_events(game_id, purchase_only=False)
    
    if not events:
        await query.edit_message_text("❌ *لا توجد إنجازات متاحة لهذه اللعبة*", parse_mode="Markdown")
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="af_back")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
        return "AF_TYPE"
    
    kb = []
    for ev in events:
        kb.append([InlineKeyboardButton(ev[2], callback_data=f"af_send_{ev[1]}")])
    # زر لفل مخصص يتيح للزبون إدخال رقم لفل يدوياً (45، 46، إلخ)
    kb.append([InlineKeyboardButton("✨ لفل مخصص", callback_data="af_custom")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="af_back")])
    
    await query.edit_message_text(
        f"🎯 *اختر الإنجاز المطلوب*\n\n🏆 {context.user_data['af_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "AF_SEND"

async def af_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_id = context.user_data["af_game_id"]
    
    purchase_events = get_af_events(game_id, purchase_only=True)
    
    if purchase_events:
        kb = []
        for ev in purchase_events:
            kb.append([InlineKeyboardButton(ev[2], callback_data=f"af_send_{ev[1]}")])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="af_back")])
        await query.edit_message_text(
            f"💰 *اختر حدث الشراء*\n\n💎 {context.user_data['af_game_name']}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return "AF_SEND"
    else:
        amounts = ["0.99", "1.99", "4.99", "9.99", "19.99", "49.99", "99.99"]
        kb = [[InlineKeyboardButton(f"💵 ${a}", callback_data=f"af_pay_{a}")] for a in amounts]
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="af_back")])
        await query.edit_message_text(
            "💰 *اختر قيمة الشراء*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return "AF_SEND"

async def af_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    
    # 🔥 جلب البيانات من user_data (بعد تعديل af_game)
    pkg = context.user_data.get("af_pkg")
    dev_key = context.user_data.get("af_dev_key")
    game_name = context.user_data.get("af_game_name", "Unknown")
    
    print(f"[DEBUG] سيتم الإرسال إلى:")
    print(f"   - Package: {pkg}")
    print(f"   - Dev Key: {dev_key[:15] if dev_key else 'None'}...")
    print(f"   - اللعبة: {game_name}")
    
    # 🔥 التحقق من أن البيانات موجودة (يجب أن تكون موجودة بعد اختيار اللعبة)
    if not pkg or not dev_key:
        await query.edit_message_text(
            "❌ *خطأ: لم يتم اختيار لعبة بعد!*\n\n"
            "الرجاء العودة إلى القائمة واختيار لعبة أولاً.",
            parse_mode="Markdown"
        )
        # العودة إلى قائمة الألعاب
        await af_show_games(update, context)
        return -1
    
    # باقي الكود كما هو (جلب GAID, AF_UID, إلخ)
    # ...
    
    # 🔥 التحقق النهائي
    if not pkg or not dev_key:
        await query.edit_message_text(
            "❌ *خطأ في بيانات اللعبة*\n\n"
            "يرجى اختيار اللعبة مرة أخرى",
            parse_mode="Markdown"
        )
        return -1
    
    # باقي الكود كما هو...
    platform = get_user_platform(uid)
    proxy = get_proxy_for_user(uid)
    
    # ... باقي الكود
    
    if platform == "ios":
        gaid = None
        af_uid = context.user_data.get("af_uid")
        idfa = context.user_data.get("af_idfa")
        idfv = context.user_data.get("af_idfv")
    else:
        gaid = context.user_data.get("af_gaid")
        af_uid = context.user_data.get("af_uid")
        idfa = None
        idfv = None
    
    if data.startswith("af_pay_"):
        amount = data.replace("af_pay_", "")
        event = "af_purchase"
        await query.edit_message_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
        status, resp = send_af(pkg, dev_key, gaid, af_uid, event, float(amount), proxy, platform, idfa, idfv)
    elif data.startswith("af_send_"):
        event = data.replace("af_send_", "")
        await query.edit_message_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
        status, resp = send_af(pkg, dev_key, gaid, af_uid, event, None, proxy, platform, idfa, idfv)
    else:
        await query.edit_message_text("❌ *حدث خطأ*", parse_mode="Markdown")
        return -1
    
    increment_user_requests(uid)
    
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"
    
    kb = [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")]]
    await query.message.reply_text(result, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return -1

async def af_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("⭐ Level / إنجاز", callback_data="af_level")],
        [InlineKeyboardButton("💰 Purchase / شراء", callback_data="af_purchase")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text("🎯 *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "AF_TYPE"

async def af_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✨ *لفل مخصص*\n\n"
        "أدخل رقم اللفل المطلوب (مثال: 45 أو 46):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 إلغاء", callback_data="af_level")]
        ])
    )
    return "AF_CUSTOM"

async def af_custom_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    digits = ''.join(filter(str.isdigit, text))
    if not digits:
        await update.message.reply_text(
            "❌ الرجاء إدخال رقم صحيح للفل (مثال: 45)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data="af_level")]
            ])
        )
        return "AF_CUSTOM"
    context.user_data["af_custom_level"] = digits
    await update.message.reply_text(
        f"✅ *تأكيد اللفل المخصص*\n\n"
        f"تم إدخال رقم اللفل: *{digits}*\n\n"
        f"هل تريد إرسال الحدث بهذا الرقم؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="af_custom_confirm")],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="af_level")]
        ])
    )
    return "AF_CUSTOM_CONFIRM"

async def af_custom_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    custom_level = context.user_data.get("af_custom_level")
    if not custom_level:
        await query.edit_message_text("❌ انتهت الجلسة، الرجاء المحاولة من جديد.")
        return -1
    pkg = context.user_data.get("af_pkg")
    dev_key = context.user_data.get("af_dev_key")
    game_name = context.user_data.get("af_game_name", "Unknown")
    if not pkg or not dev_key:
        await query.edit_message_text(
            "❌ *خطأ: لم يتم اختيار لعبة بعد!*\n\nالرجاء العودة إلى القائمة واختيار لعبة أولاً.",
            parse_mode="Markdown"
        )
        await af_show_games(update, context)
        return -1
    platform = get_user_platform(uid)
    proxy = get_proxy_for_user(uid)
    if platform == "ios":
        gaid = None
        af_uid = context.user_data.get("af_uid")
        idfa = context.user_data.get("af_idfa")
        idfv = context.user_data.get("af_idfv")
    else:
        gaid = context.user_data.get("af_gaid")
        af_uid = context.user_data.get("af_uid")
        idfa = None
        idfv = None
    # نرسل الحدث بنفس الطريقة الأساسية مع تمرير رقم اللفل المخصص
    event = "af_level_custom"
    await query.edit_message_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
    status, resp = send_af(pkg, dev_key, gaid, af_uid, event, None, proxy, platform, idfa, idfv, custom_level=custom_level)
    increment_user_requests(uid)
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"
    kb = [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main")]]
    await query.message.reply_text(result, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return -1

# ==================================================================================
#                               Singular
# ==================================================================================
async def singular_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🎮 عرض الألعاب", callback_data="singular_show_games")],
        [InlineKeyboardButton("🔍 بحث", callback_data="singular_search_game")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text("🌟 *Singular*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "SINGULAR_MAIN"

async def singular_show_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"sgame_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "SINGULAR_GAME"

async def singular_search_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 *أدخل اسم اللعبة*", parse_mode="Markdown")
    return "SINGULAR_SEARCH"

async def singular_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    games = c_main.execute("SELECT id, display_name, emoji FROM games_singular WHERE display_name LIKE ?", (f"%{text}%",)).fetchall()
    if not games:
        await update.message.reply_text("❌ *لا يوجد*", parse_mode="Markdown")
        return "SINGULAR_SEARCH"
    kb = [[InlineKeyboardButton(f"{g[2]} {g[1]}", callback_data=f"sgame_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")])
    await update.message.reply_text("✅ *نتائج البحث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "SINGULAR_GAME"

async def singular_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.replace("sgame_", ""))
    game = c_main.execute("SELECT id, name, display_name, package, app_key, emoji FROM games_singular WHERE id = ?", (gid,)).fetchone()
    
    context.user_data["sg_game_id"] = game[0]
    context.user_data["sg_game_name"] = game[2]
    context.user_data["sg_package"] = game[3]
    context.user_data["sg_app_key"] = game[4]
    
    # 🔥 IMPORTANT: فرض Android مباشرة
    context.user_data["sg_platform"] = "android"
    
    print(f"[DEBUG] Singular Game - Platform forced to: android")
    
    # 🔥 طلب GAID مباشرة (بدون iOS)
    await query.edit_message_text(
        f"{game[5]} *{game[2]}*\n\n🤖 *Android - Singular*\n📱 *أدخل AIFA (GAID):*\nمثال: `8de8604d-1318-4fd0-907c-402ea9de2529`",
        parse_mode="Markdown"
    )
    return "SINGULAR_AIFA"

async def singular_idfa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sg_idfa"] = update.message.text.strip()
    await update.message.reply_text("🍎 *أدخل IDFV:*\nمثال: `12345678-1234-1234-1234-123456789012`\n\n⚠️ *مطلوب لـ iOS (IDFV)*", parse_mode="Markdown")
    return "SINGULAR_IDFV"

async def singular_idfv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sg_idfv"] = update.message.text.strip()
    await update.message.reply_text("🆔 *أدخل Custom User ID:*\nمثال: `your_user_id_123`\n\n⚠️ *مطلوب لـ iOS (Custom User ID)*", parse_mode="Markdown")
    return "SINGULAR_UID"

async def singular_uid_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sg_uid"] = update.message.text.strip()
    context.user_data["sg_platform"] = "ios"
    await show_singular_events(update, context)
    return -1

async def singular_aifa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sg_aifa"] = update.message.text.strip()
    context.user_data["sg_platform"] = "android"  # 🔥 تأكد من Android
    print(f"[DEBUG] Singular AIFA: {context.user_data['sg_aifa']}")
    print(f"[DEBUG] Singular Platform: {context.user_data['sg_platform']}")
    await update.message.reply_text(
        "🆔 *أدخل Custom User ID:*\nمثال: `your_user_id_123`\n\n⚠️ *اختياري - اكتب 'تخطي' أو اتركه فارغاً*",
        parse_mode="Markdown"
    )
    return "SINGULAR_UID"

async def singular_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid_text = update.message.text.strip()
    if uid_text and uid_text.lower() != 'تخطي':
        context.user_data["sg_uid"] = uid_text
    else:
        context.user_data["sg_uid"] = ""
    
    context.user_data["sg_platform"] = "android"
    print(f"[DEBUG] Singular Final - Platform: android")
    print(f"[DEBUG] Singular Final - AIFA: {context.user_data.get('sg_aifa')}")
    print(f"[DEBUG] Singular Final - UID: {context.user_data.get('sg_uid')}")
    
    await show_singular_events(update, context)
    return -1

async def show_singular_events(update, context):
    events = get_singular_events(context.user_data["sg_game_id"])
    
    if not events:
        kb = [[InlineKeyboardButton("➕ إضافة حدث", callback_data="admin_add_event")], [InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")]]
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text(
            f"❌ *لا توجد أحداث لهذه اللعبة*\n\n🌟 *{context.user_data['sg_game_name']}*\n\n⚠️ يرجى إضافة أحداث من لوحة التحكم",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return
    
    kb = []
    for ev in events:
        kb.append([InlineKeyboardButton(f"🌟 {ev[2]}", callback_data=f"singular_send_{ev[1]}")])
    
    kb.append([InlineKeyboardButton("✨ حدث مخصص", callback_data="singular_custom")])
    kb.append([InlineKeyboardButton("🔢 لفل مخصص", callback_data="singular_custom_level")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")])
    
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(
        f"🎯 *اختر الحدث*\n🌟 {context.user_data['sg_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

def send_singular(event_name, aifa, uid, package, app_key, level=None, proxy=None, platform="android", idfa=None, idfv=None):
    import requests
    import json
    import time
    
    # 🔥 استخدام GET كما في الرابط الشغال
    base_url = "https://s2s.singular.net/api/v1/evt"
    
    # بناء المعاملات (parameters)
    params = {
        "a": app_key,           # App Key
        "p": "Android",         # المنصة (ثابتة زي الرابط)
        "i": package,           # Package Name (لاحظ: i تحتوي على package)
        "aifa": aifa,           # GAID
        "u": uid if uid else "", # Custom User ID
        "utime": int(time.time()),  # الوقت الحالي بالثواني
        "n": event_name         # اسم الحدث
    }
    # إضافة رقم اللفل إن وُجد (للأحداث المخصصة)
    if level:
        params["level"] = level
    
    # تنظيف المعاملات الفارغة
    params = {k: v for k, v in params.items() if v}
    
    print(f"[DEBUG] Singular Request URL: {base_url}")
    print(f"[DEBUG] Singular Params: {json.dumps(params, indent=2)}")
    
    headers = {
        "User-Agent": "SingularS2S/1.0",
        "Accept": "application/json"
    }
    
    try:
        if proxy:
            r = requests.get(base_url, params=params, headers=headers, timeout=30, proxies=proxy)
        else:
            r = requests.get(base_url, params=params, headers=headers, timeout=30)
        
        print(f"[DEBUG] Singular Response: {r.status_code} - {r.text[:200]}")
        
        if r.status_code == 200:
            return 200, r.text
        return r.status_code, r.text
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        return 500, str(e)

async def singular_resend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    game_id = int(query.data.replace("singular_resend_", ""))
    game = c_main.execute("SELECT id, name, display_name, package, app_key, emoji FROM games_singular WHERE id = ?", (game_id,)).fetchone()
    
    context.user_data["sg_game_id"] = game_id
    context.user_data["sg_game_name"] = game[2]
    context.user_data["sg_package"] = game[3]
    context.user_data["sg_app_key"] = game[4]
    
    events = get_singular_events(game_id)
    
    if not events:
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")]]
        await query.edit_message_text(
            f"❌ *لا توجد أحداث لهذه اللعبة*\n🌟 {game[0]}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return -1
    
    kb = []
    for ev in events:
        kb.append([InlineKeyboardButton(f"🌟 {ev[2]}", callback_data=f"singular_send_{ev[1]}")])
    
    kb.append([InlineKeyboardButton("✨ حدث مخصص", callback_data="singular_custom")])
    kb.append([InlineKeyboardButton("🔢 لفل مخصص", callback_data="singular_custom_level")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")])
    
    await query.edit_message_text(
        f"🎯 *اختر الحدث*\n🌟 {context.user_data['sg_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def singular_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✨ *حدث مخصص*\n\n📝 *أدخل اسم الحدث:*\nمثال: `level_50` أو `Complete_Level`",
        parse_mode="Markdown"
    )
    return "SINGULAR_CUSTOM"

async def singular_custom_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_name = update.message.text.strip()

    pkg = context.user_data["sg_package"]
    app_key = context.user_data["sg_app_key"]
    proxy = get_proxy_for_user(update.effective_user.id)
    platform = context.user_data.get("sg_platform", "android")

    await update.message.reply_text("📤 *جاري الإرسال...*", parse_mode="Markdown")

    if platform == "ios":
        idfa = context.user_data.get("sg_idfa")
        idfv = context.user_data.get("sg_idfv")
        uid = context.user_data.get("sg_uid")
        status, resp = send_singular(event_name, None, uid, pkg, app_key, None, proxy, "ios", idfa, idfv)
    else:
        aifa = context.user_data.get("sg_aifa")
        uid = context.user_data.get("sg_uid")
        status, resp = send_singular(event_name, aifa, uid, pkg, app_key, None, proxy, "android")

    increment_user_requests(update.effective_user.id)

    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"

    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"singular_resend_{context.user_data['sg_game_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")]
    ]

    await update.message.reply_text(
        f"{result}\n📝 *الحدث:* {event_name}\n🎮 *اللعبة:* {context.user_data['sg_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def singular_custom_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # نخزن علم يدل أن المستخدم بانتظار إدخال رقم لفل مخصص لـ Singular
    context.user_data["awaiting_sg_level"] = True
    await query.edit_message_text(
        "✨ *لفل مخصص*\n\n"
        "أدخل رقم اللفل المطلوب (مثال: 45 أو 46) وسيُرسل الحدث فوراً:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 إلغاء", callback_data=f"singular_resend_{context.user_data.get('sg_game_id', '')}")]
        ])
    )
    return "SINGULAR_CUSTOM_LEVEL"

async def singular_custom_level_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    digits = ''.join(filter(str.isdigit, text))
    game_id = context.user_data.get("sg_game_id", "")
    cancel_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 إلغاء", callback_data=f"singular_resend_{game_id}")]
    ])
    if not digits:
        await update.message.reply_text(
            "❌ الرجاء إدخال رقم صحيح للفل (مثال: 45)",
            reply_markup=cancel_kb
        )
        return "SINGULAR_CUSTOM_LEVEL"
    pkg = context.user_data.get("sg_package")
    app_key = context.user_data.get("sg_app_key")
    aifa = context.user_data.get("sg_aifa", "")
    uid = context.user_data.get("sg_uid", "")
    game_name = context.user_data.get("sg_game_name", "")
    if not pkg:
        await update.message.reply_text("❌ خطأ: Package Name غير موجود، الرجاء إعادة اختيار اللعبة", reply_markup=cancel_kb)
        return -1
    if not app_key:
        await update.message.reply_text("❌ خطأ: App Key غير موجود، الرجاء إعادة اختيار اللعبة", reply_markup=cancel_kb)
        return -1
    if not aifa:
        await update.message.reply_text("❌ خطأ: GAID/AIFA غير موجود، الرجاء إعادة اختيار اللعبة وإدخال GAID صحيح", reply_markup=cancel_kb)
        return -1
    events = get_singular_events(game_id) if game_id else []
    if events:
        event_name = events[0][1]
    else:
        event_name = "level"

    # إذا كان اسم الحدث قالباً ينتهي بـ _ نُضيف رقم اللفل مباشرةً إليه
    # بنفس طريقة باقي الأحداث (مثال: mn_level_ + 45 = mn_level_45)
    if event_name.endswith("_"):
        event_name = event_name + digits
        level_param = None
    else:
        level_param = digits

    proxy = get_proxy_for_user(update.effective_user.id)
    await update.message.reply_text("📤 *جاري الإرسال فوراً...*", parse_mode="Markdown")
    status, resp = send_singular(event_name, aifa, uid, pkg, app_key, level_param, proxy, "android")
    increment_user_requests(update.effective_user.id)
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})\n`{resp[:100]}`"
    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"singular_resend_{game_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")]
    ]
    await update.message.reply_text(
        f"{result}\n📝 *الحدث:* `{event_name}`\n🔢 *رقم اللفل:* {digits}\n🎮 *اللعبة:* {game_name}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def singular_custom_level_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    custom_level = context.user_data.get("sg_custom_level")
    if not custom_level:
        await query.edit_message_text("❌ انتهت الجلسة، الرجاء المحاولة من جديد.")
        return -1
    pkg = context.user_data["sg_package"]
    app_key = context.user_data["sg_app_key"]
    proxy = get_proxy_for_user(query.from_user.id)
    platform = context.user_data.get("sg_platform", "android")
    event_name = "level_custom"
    await query.message.reply_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
    if platform == "ios":
        idfa = context.user_data.get("sg_idfa")
        idfv = context.user_data.get("sg_idfv")
        uid = context.user_data.get("sg_uid")
        status, resp = send_singular(event_name, None, uid, pkg, app_key, custom_level, proxy, "ios", idfa, idfv)
    else:
        aifa = context.user_data.get("sg_aifa")
        uid = context.user_data.get("sg_uid")
        status, resp = send_singular(event_name, aifa, uid, pkg, app_key, custom_level, proxy, "android")
    increment_user_requests(query.from_user.id)
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"
    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"singular_resend_{context.user_data['sg_game_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="singular_menu")]
    ]
    await query.message.reply_text(
        f"{result}\n📝 *الحدث:* {event_name}\n🔢 *رقم اللفل:* {custom_level}\n🎮 *اللعبة:* {context.user_data['sg_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

# ==================================================================================
#                               Adjust
# ==================================================================================
# ==================================================================================
#                               Adjust
# ==================================================================================

async def adj_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🎮 عرض الألعاب", callback_data="adj_show_games")],
        [InlineKeyboardButton("🔍 بحث", callback_data="adj_search_game")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text("📊 *Adjust*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADJ_MAIN"

async def adj_show_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"adjgame_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADJ_GAME"

async def adj_search_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 *أدخل اسم اللعبة*", parse_mode="Markdown")
    return "ADJ_SEARCH"

async def adj_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    games = c_main.execute("SELECT id, display_name, emoji FROM games_adj WHERE display_name LIKE ?", (f"%{text}%",)).fetchall()
    if not games:
        await update.message.reply_text("❌ *لا يوجد*", parse_mode="Markdown")
        return "ADJ_SEARCH"
    kb = [[InlineKeyboardButton(f"{g[2]} {g[1]}", callback_data=f"adjgame_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")])
    await update.message.reply_text("✅ *نتائج البحث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADJ_GAME"

async def adj_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.replace("adjgame_", ""))
    game = c_main.execute("SELECT id, name, display_name, app_token, emoji FROM games_adj WHERE id = ?", (gid,)).fetchone()
    context.user_data.update({"adj_game_id": game[0], "adj_game_name": game[2], "adj_app_token": game[3]})
    
    platform = get_user_platform(query.from_user.id)
    if platform == "ios":
        await query.edit_message_text(f"{game[4]} *{game[2]}*\n\n🍎 *iOS*\n📱 *أدخل IDFA:*\nمثال: `12345678-1234-1234-1234-123456789012`\n\n⚠️ *مطلوب لـ Adjust (سيتم استخدامه كـ GPS ADID)*", parse_mode="Markdown")
        return "ADJ_ADID"
    else:
        await query.edit_message_text(f"{game[4]} *{game[2]}*\n\n🤖 *Android*\n📱 *أدخل GPS ADID:*\nمثال: `8de8604d-1318-4fd0-907c-402ea9de2529`\n\n⚠️ *مطلوب لـ Android*", parse_mode="Markdown")
        return "ADJ_ADID"

async def adj_adid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adj_gps"] = update.message.text.strip()
    
    events = get_adj_events(context.user_data["adj_game_id"])
    
    if not events:
        kb = [[InlineKeyboardButton("➕ إضافة حدث", callback_data="admin_add_event")], [InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")]]
        await update.message.reply_text(
            f"❌ *لا توجد أحداث لهذه اللعبة*\n\n📊 *{context.user_data['adj_game_name']}*\n\n⚠️ يرجى إضافة أحداث من لوحة التحكم",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return -1
    
    kb = []
    for ev in events:
        display = ev[3] if ev[3] else ev[1]
        event_id = ev[0]
        kb.append([InlineKeyboardButton(f"📊 {display}", callback_data=f"adj_send_{event_id}")])
    
    kb.append([InlineKeyboardButton("✨ حدث مخصص", callback_data="adj_custom")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")])
    
    await update.message.reply_text(
        f"🎯 *اختر الحدث*\n📊 {context.user_data['adj_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def adj_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    event_id_str = query.data.replace("adj_send_", "")
    try:
        event_id = int(event_id_str)
    except ValueError:
        await query.edit_message_text("❌ خطأ في معرف الحدث", parse_mode="Markdown")
        return -1
    
    ev = c_main.execute("SELECT event_token, display_name FROM events_adj WHERE id = ?", (event_id,)).fetchone()
    if not ev:
        await query.edit_message_text("❌ حدث غير موجود", parse_mode="Markdown")
        return -1
    
    event_token = ev[0]
    display_name = ev[1] if ev[1] else event_token
    
    app_token = context.user_data["adj_app_token"]
    gps = context.user_data["adj_gps"]
    proxy = get_proxy_for_user(query.from_user.id)
    
    await query.edit_message_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
    
    # 🔥 استخدم الدالة المعدلة
    status, resp = send_adj(app_token, event_token, gps, proxy)
    
    increment_user_requests(query.from_user.id)
    
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"
    
    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"adj_resend_{context.user_data['adj_game_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")]
    ]
    
    await query.message.reply_text(
        f"{result}\n📝 *الحدث:* {display_name}\n🎮 *اللعبة:* {context.user_data['adj_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def adj_resend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not query.data or not query.data.startswith("adj_resend_"):
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    
    try:
        game_id = int(query.data.replace("adj_resend_", ""))
    except ValueError:
        await query.edit_message_text("❌ خطأ في معرف اللعبة", parse_mode="Markdown")
        return -1
    
    game = c_main.execute("SELECT display_name FROM games_adj WHERE id = ?", (game_id,)).fetchone()
    if not game:
        await query.edit_message_text("❌ اللعبة غير موجودة", parse_mode="Markdown")
        return -1
    
    context.user_data["adj_game_id"] = game_id
    context.user_data["adj_game_name"] = game[0]
    
    events = get_adj_events(game_id)
    
    if not events:
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")]]
        await query.edit_message_text(
            f"❌ *لا توجد أحداث لهذه اللعبة*\n📊 {game[0]}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return -1
    
    kb = []
    for ev in events:
        display = ev[3] if ev[3] else ev[1]
        event_id = ev[0]
        kb.append([InlineKeyboardButton(f"📊 {display}", callback_data=f"adj_send_{event_id}")])
    
    kb.append([InlineKeyboardButton("✨ حدث مخصص", callback_data="adj_custom")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")])
    
    await query.edit_message_text(
        f"🎯 *اختر الحدث*\n📊 {context.user_data['adj_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def adj_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_adj_level"] = True
    await query.edit_message_text(
        "✨ *لفل مخصص*\n\n"
        "أدخل رقم اللفل المطلوب (مثال: 45 أو 46) وسيُرسل الحدث فوراً:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 إلغاء", callback_data=f"adj_resend_{context.user_data.get('adj_game_id', '')}")]
        ])
    )
    return "ADJ_CUSTOM_LEVEL"

async def adj_custom_level_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    digits = ''.join(filter(str.isdigit, text))
    if not digits:
        await update.message.reply_text(
            "❌ الرجاء إدخال رقم صحيح للفل (مثال: 45)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 إلغاء", callback_data=f"adj_resend_{context.user_data.get('adj_game_id', '')}")]
            ])
        )
        return "ADJ_CUSTOM_LEVEL"
    context.user_data.pop("awaiting_adj_level", None)
    event_token = digits
    app_token = context.user_data["adj_app_token"]
    gps = context.user_data["adj_gps"]
    proxy = get_proxy_for_user(update.effective_user.id)
    await update.message.reply_text("📤 *جاري الإرسال فوراً...*", parse_mode="Markdown")
    status, resp = send_adj(app_token, event_token, gps, proxy)
    increment_user_requests(update.effective_user.id)
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"
    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"adj_resend_{context.user_data['adj_game_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")]
    ]
    await update.message.reply_text(
        f"{result}\n🔢 *رقم اللفل:* {digits}\n🎮 *اللعبة:* {context.user_data['adj_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

async def adj_custom_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_token = update.message.text.strip()
    proxy = get_proxy_for_user(update.effective_user.id)
    
    await update.message.reply_text("📤 *جاري الإرسال...*", parse_mode="Markdown")
    status, resp = send_adj(context.user_data["adj_app_token"], event_token, context.user_data["adj_gps"], proxy)
    increment_user_requests(update.effective_user.id)
    
    if status == 200:
        result = "✅ *تم الإرسال بنجاح!*"
    else:
        result = f"❌ *فشل الإرسال* (HTTP {status})"
    
    kb = [
        [InlineKeyboardButton("🎯 حدث اخر", callback_data=f"adj_resend_{context.user_data['adj_game_id']}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="adj_menu")]
    ]
    
    await update.message.reply_text(
        f"{result}\n📝 *الحدث:* {event_token}\n🎮 *اللعبة:* {context.user_data['adj_game_name']}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return -1

# ==================================================================================
#                             مزرعة الجمبرة
# ==================================================================================
# ==================================================================================
#                             مزرعة الجمبرة (تابع)
# ==================================================================================
# ==================================================================================
#                             مزرعة الجمبرة (المطورة)
# ==================================================================================

# قاموس لتخزين المهام المجدولة
scheduled_jobs = {}

async def jumper_farm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🌾 مزرعة جديدة", callback_data="farm_new")],
        [InlineKeyboardButton("📋 مزارعي", callback_data="farm_list")],
        [InlineKeyboardButton("⚙️ وضع خاص", callback_data="farm_special")],
        [InlineKeyboardButton("⏹️ إيقاف مزرعة", callback_data="farm_stop")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text(
        "🌾 *مزرعة الجمبرة المطورة* 🌾\n\n"
        "✨ *الأوضاع المتاحة:*\n"
        "• 🛡️ وضع آمن: 1 لفل/يوم\n"
        "• ⚡ وضع عادي: 3 لفل/يوم\n"
        "• 🚀 وضع سريع: 5 لفل/يوم\n"
        "• 🎮 وضع خاص: تحكم كامل بالوقت لكل لفل\n\n"
        "⚠️ *يجب إعداد بروكسي أولاً*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "FARM_MAIN"

async def farm_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    tasks = c_main.execute("SELECT id, task_name, platform, game_name, start_level, end_level, current_level, status, mode FROM farm_tasks WHERE user_id = ? AND status='running' ORDER BY created_date DESC", (uid,)).fetchall()
    if not tasks:
        await query.edit_message_text("📋 *لا توجد مزارع نشطة*", parse_mode="Markdown")
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]]
        await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
        return -1
    
    txt = "📋 *مزارعك النشطة*\n\n"
    for t in tasks:
        mode_name = {"safe": "🛡️ آمن", "normal": "⚡ عادي", "fast": "🚀 سريع", "special": "🎮 خاص"}.get(t[8], t[8])
        txt += f"• *{t[1]}*\n┣ 🎮 {t[3]}\n┣ 🎯 {t[4]} → {t[5]} (حالياً {t[6]})\n┣ 📊 الوضع: {mode_name}\n┣ 📌 الحالة: {t[7]}\n┗ 🆔 `{t[0]}`\n\n"
    
    kb = [
        [InlineKeyboardButton("🔧 تعديل مزرعة", callback_data="farm_edit_list")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]
    ]
    await query.edit_message_text(txt[:4000], reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return -1

async def farm_edit_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض المزارع لتعديلها"""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    tasks = c_main.execute("SELECT id, task_name, game_name, current_level, end_level FROM farm_tasks WHERE user_id = ? AND status='running'", (uid,)).fetchall()
    
    if not tasks:
        await query.edit_message_text("📋 *لا توجد مزارع نشطة للتعديل*", parse_mode="Markdown")
        await asyncio.sleep(1)
        await farm_list(update, context)
        return -1
    
    kb = []
    for t in tasks:
        kb.append([InlineKeyboardButton(f"🎮 {t[2]} - {t[1][:20]}", callback_data=f"farm_edit_{t[0]}")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_list")])
    
    await query.edit_message_text("🔧 *اختر المزرعة لتعديلها*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_EDIT_SELECT"

async def farm_edit_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل مزرعة محددة"""
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("farm_edit_", ""))
    
    task = c_main.execute("SELECT id, task_name, game_name, current_level, end_level, platform FROM farm_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        await query.edit_message_text("❌ *المزرعة غير موجودة*", parse_mode="Markdown")
        return -1
    
    context.user_data["edit_task_id"] = task_id
    context.user_data["edit_task_name"] = task[1]
    context.user_data["edit_game_name"] = task[2]
    context.user_data["edit_current_level"] = task[3]
    context.user_data["edit_end_level"] = task[4]
    
    # جلب المستويات من جدول الأحداث
    levels_list = []
    if task[5] == "af":
        events = get_af_events(task[0], False)  # هذا تقريبي، يحتاج تعديل حسب هيكل قاعدة البيانات
    elif task[5] == "adj":
        events = get_adj_events(task[0])
    else:
        events = get_singular_events(task[0])
    
    kb = [
        [InlineKeyboardButton("⚡ ضرب المستوى الحالي فوراً", callback_data=f"farm_hit_now_{task[0]}")],
        [InlineKeyboardButton("🗑️ حذف مستوى معين", callback_data=f"farm_delete_level_{task[0]}")],
        [InlineKeyboardButton("📊 تغيير المستوى الحالي", callback_data=f"farm_change_level_{task[0]}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="farm_edit_list")]
    ]
    
    await query.edit_message_text(
        f"🔧 *تعديل المزرعة*\n\n"
        f"🎮 *اللعبة:* {task[2]}\n"
        f"📋 *المهمة:* `{task[1]}`\n"
        f"🎯 *المستوى الحالي:* {task[3]}\n"
        f"🏁 *المستوى النهائي:* {task[4]}\n"
        f"📊 *المتبقي:* {task[4] - task[3] + 1} مستوى\n\n"
        f"✨ *اختر الإجراء:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "FARM_EDIT_ACTION"

async def farm_hit_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ضرب المستوى الحالي فوراً"""
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("farm_hit_now_", ""))
    uid = query.from_user.id
    
    task = c_main.execute("SELECT * FROM farm_tasks WHERE id = ? AND user_id = ?", (task_id, uid)).fetchone()
    if not task:
        await query.edit_message_text("❌ *المزرعة غير موجودة*", parse_mode="Markdown")
        return -1
    
    proxy = get_proxy_for_user(uid)
    user_platform = get_user_platform(uid)
    
    await query.edit_message_text("⚡ *جاري ضرب المستوى فوراً...*", parse_mode="Markdown")
    
    success = False
    if task['platform'] == "af":
        game = c_main.execute("SELECT package, dev_key FROM games_af WHERE id = ?", (task['game_id'],)).fetchone()
        if game:
            event_name = f"level_{task['current_level']}"
            if user_platform == "ios":
                status, resp = send_af(game['package'], game['dev_key'], None, task['af_uid'], event_name, None, proxy, "ios", task['idfa'], task['idfv'])
            else:
                status, resp = send_af(game['package'], game['dev_key'], task['gaid'], task['af_uid'], event_name, None, proxy, "android")
            success = status == 200
    
    elif task['platform'] == "adj":
        game = c_main.execute("SELECT app_token FROM games_adj WHERE id = ?", (task['game_id'],)).fetchone()
        if game:
            ev = c_main.execute("SELECT event_token FROM events_adj WHERE game_id = ? AND level_value = ?", (task['game_id'], task['current_level'])).fetchone()
            if ev:
                status, resp = send_adj(game['app_token'], ev['event_token'], task['gps_adid'], proxy)
                success = status == 200
    
    elif task['platform'] == "singular":
        game = c_main.execute("SELECT package, app_key FROM games_singular WHERE id = ?", (task['game_id'],)).fetchone()
        if game:
            ev = c_main.execute("SELECT event_name FROM events_singular WHERE game_id = ?", (task['game_id'],)).fetchone()
            if ev:
                if user_platform == "ios":
                    status, resp = send_singular(ev['event_name'], None, task['uid'], game['package'], game['app_key'], task['current_level'], proxy, "ios", task['idfa'], task['idfv'])
                else:
                    status, resp = send_singular(ev['event_name'], task['aifa'], task['uid'], game['package'], game['app_key'], task['current_level'], proxy, "android")
                success = status == 200
    
    if success:
        new_level = task['current_level'] + 1
        c_main.execute("UPDATE farm_tasks SET current_level = ?, last_run = ?, completed_levels = completed_levels + 1 WHERE id = ?", 
                       (new_level, datetime.now().isoformat(), task['id']))
        conn_main.commit()
        
        remaining = task['end_level'] - new_level
        await query.message.reply_text(
            f"✅ *تم ضرب المستوى {task['current_level']} بنجاح!*\n\n"
            f"🎮 {task['game_name']}\n"
            f"📊 المتبقي: {remaining + 1} مستوى\n"
            f"🎯 المستوى الحالي: {new_level}",
            parse_mode="Markdown"
        )
        
        if remaining >= 0:
            await send_farm_notification(context, uid, task['id'], task['current_level'], remaining, task['end_level'], task['game_name'])
    else:
        await query.message.reply_text(f"❌ *فشل ضرب المستوى {task['current_level']}*", parse_mode="Markdown")
    
    await asyncio.sleep(1)
    await farm_edit_task(update, context)
    return -1

async def farm_delete_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف مستوى معين من المزرعة (تخطيه)"""
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("farm_delete_level_", ""))
    
    await query.edit_message_text(
        "🗑️ *حذف مستوى معين*\n\n"
        "📝 *أدخل رقم المستوى الذي تريد حذفه (تخطيه):*\n"
        f"📊 المستويات المتاحة: من المستوى الحالي إلى النهائي\n\n"
        "⚠️ *سيتم تخطي هذا المستوى وعدم ضربه*",
        parse_mode="Markdown"
    )
    return "FARM_DELETE_LEVEL_INPUT"

async def farm_delete_level_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة حذف مستوى معين"""
    try:
        level_to_delete = int(update.message.text.strip())
        task_id = context.user_data.get("edit_task_id")
        
        task = c_main.execute("SELECT current_level, end_level FROM farm_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            await update.message.reply_text("❌ *المزرعة غير موجودة*", parse_mode="Markdown")
            return -1
        
        if level_to_delete < task['current_level'] or level_to_delete > task['end_level']:
            await update.message.reply_text(f"❌ *المستوى خارج النطاق*\nالمستوى الحالي: {task['current_level']} → النهائي: {task['end_level']}", parse_mode="Markdown")
            return "FARM_DELETE_LEVEL_INPUT"
        
        # إذا كان المستوى المطلوب حذفه هو المستوى الحالي، نزيده
        if level_to_delete == task['current_level']:
            c_main.execute("UPDATE farm_tasks SET current_level = current_level + 1 WHERE id = ?", (task_id,))
            conn_main.commit()
            await update.message.reply_text(f"✅ *تم تخطي المستوى {level_to_delete} بنجاح*\nالمستوى الحالي الآن: {task['current_level'] + 1}", parse_mode="Markdown")
        else:
            # نضع علامة أن هذا المستوى متخطى (نحتاج جدول إضافي، لكن سنعدل current_level فقط)
            await update.message.reply_text(f"⚠️ *لا يمكن حذف مستوى غير الحالي مباشرة*\nقم بضرب المستويات بالترتيب أو استخدم خيار تغيير المستوى الحالي", parse_mode="Markdown")
        
    except ValueError:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_DELETE_LEVEL_INPUT"
    
    await farm_edit_task(update, context)
    return -1

async def farm_change_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغيير المستوى الحالي يدوياً"""
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.replace("farm_change_level_", ""))
    context.user_data["edit_task_id"] = task_id
    
    await query.edit_message_text(
        "📊 *تغيير المستوى الحالي*\n\n"
        "📝 *أدخل رقم المستوى الجديد:*\n"
        "⚠️ *سيتم تعيين هذا المستوى كالمستوى الحالي*",
        parse_mode="Markdown"
    )
    return "FARM_CHANGE_LEVEL_INPUT"

async def farm_change_level_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تغيير المستوى الحالي"""
    try:
        new_level = int(update.message.text.strip())
        task_id = context.user_data.get("edit_task_id")
        
        task = c_main.execute("SELECT start_level, end_level FROM farm_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            await update.message.reply_text("❌ *المزرعة غير موجودة*", parse_mode="Markdown")
            return -1
        
        if new_level < task['start_level'] or new_level > task['end_level']:
            await update.message.reply_text(f"❌ *المستوى خارج النطاق*\nالنطاق: {task['start_level']} → {task['end_level']}", parse_mode="Markdown")
            return "FARM_CHANGE_LEVEL_INPUT"
        
        c_main.execute("UPDATE farm_tasks SET current_level = ? WHERE id = ?", (new_level, task_id))
        conn_main.commit()
        await update.message.reply_text(f"✅ *تم تغيير المستوى الحالي إلى {new_level}*", parse_mode="Markdown")
        
    except ValueError:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_CHANGE_LEVEL_INPUT"
    
    await farm_edit_task(update, context)
    return -1

# ==================================================================================
#                             وضع خاص (Special Mode)
# ==================================================================================

async def farm_special(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء إنشاء مزرعة بالوضع الخاص"""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    proxy = get_proxy_for_user(uid)
    if not proxy:
        await query.edit_message_text(
            "❌ *لا يمكن إنشاء مزرعة بدون بروكسي!*\n\nيرجى إضافة بروكسي أولاً",
            parse_mode="Markdown"
        )
        await asyncio.sleep(2)
        await jumper_farm_menu(update, context)
        return -1
    
    context.user_data["farm_mode"] = "special"
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="farm_special_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="farm_special_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="farm_special_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="jumper_farm")]
    ]
    await query.edit_message_text("🎮 *وضع خاص - اختر المنصة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_SPECIAL_PLATFORM"

async def farm_special_platform_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["farm_platform"] = "af"
    games = get_all_games_af()
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"farm_special_game_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_special")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_SPECIAL_GAME"

async def farm_special_platform_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["farm_platform"] = "adj"
    games = get_all_games_adj()
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"farm_special_game_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_special")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_SPECIAL_GAME"

async def farm_special_platform_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["farm_platform"] = "singular"
    games = get_all_games_singular()
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"farm_special_game_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="farm_special")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "FARM_SPECIAL_GAME"

async def farm_special_game_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    platform = parts[3]
    game_id = int(parts[4])
    context.user_data["farm_game_id"] = game_id
    
    if platform == "af":
        game = c_main.execute("SELECT display_name FROM games_af WHERE id = ?", (game_id,)).fetchone()
        context.user_data["farm_game_name"] = game[0]
        user_platform = get_user_platform(query.from_user.id)
        if user_platform == "ios":
            await query.edit_message_text("🍎 *iOS - AppsFlyer*\n\n📱 *أدخل IDFA:*", parse_mode="Markdown")
            return "FARM_SPECIAL_IDFA_AF"
        else:
            await query.edit_message_text("🤖 *Android - AppsFlyer*\n\n📱 *أدخل GAID:*", parse_mode="Markdown")
            return "FARM_SPECIAL_GAID"
    elif platform == "adj":
        game = c_main.execute("SELECT display_name FROM games_adj WHERE id = ?", (game_id,)).fetchone()
        context.user_data["farm_game_name"] = game[0]
        user_platform = get_user_platform(query.from_user.id)
        if user_platform == "ios":
            await query.edit_message_text("🍎 *iOS - Adjust*\n\n📱 *أدخل IDFA:*\n(سيتم استخدامه كـ GPS ADID)", parse_mode="Markdown")
            return "FARM_SPECIAL_GPS_ADID"
        else:
            await query.edit_message_text("🤖 *Android - Adjust*\n\n📱 *أدخل GPS ADID:*", parse_mode="Markdown")
            return "FARM_SPECIAL_GPS_ADID"
    else:
        game = c_main.execute("SELECT display_name FROM games_singular WHERE id = ?", (game_id,)).fetchone()
        context.user_data["farm_game_name"] = game[0]
        user_platform = get_user_platform(query.from_user.id)
        if user_platform == "ios":
            await query.edit_message_text("🍎 *iOS - Singular*\n\n📱 *أدخل IDFA:*", parse_mode="Markdown")
            return "FARM_SPECIAL_IDFA_SINGULAR"
        else:
            await query.edit_message_text("🤖 *Android - Singular*\n\n📱 *أدخل AIFA (GAID):*", parse_mode="Markdown")
            return "FARM_SPECIAL_AIFA"

# دوال جمع البيانات للوضع الخاص (مشابهة للوضع العادي)
async def farm_special_idfa_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfa"] = update.message.text.strip()
    await update.message.reply_text("🍎 *أدخل IDFV:*", parse_mode="Markdown")
    return "FARM_SPECIAL_IDFV_AF"

async def farm_special_idfv_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfv"] = update.message.text.strip()
    await update.message.reply_text("📱 *أدخل AF ID (AppsFlyer ID):*", parse_mode="Markdown")
    return "FARM_SPECIAL_AF_UID"

async def farm_special_af_uid_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_af_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_SPECIAL_START_LEVEL"

async def farm_special_gaid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_gaid"] = update.message.text.strip()
    await update.message.reply_text("📱 *أدخل AF UID (AppsFlyer ID):*", parse_mode="Markdown")
    return "FARM_SPECIAL_AF_UID"

async def farm_special_af_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_af_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_SPECIAL_START_LEVEL"

async def farm_special_gps_adid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_gps"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_SPECIAL_START_LEVEL"

async def farm_special_idfa_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfa"] = update.message.text.strip()
    await update.message.reply_text("🍎 *أدخل IDFV:*", parse_mode="Markdown")
    return "FARM_SPECIAL_IDFV_SINGULAR"

async def farm_special_idfv_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_idfv"] = update.message.text.strip()
    await update.message.reply_text("🆔 *أدخل Custom User ID:*", parse_mode="Markdown")
    return "FARM_SPECIAL_SINGULAR_UID"

async def farm_special_singular_uid_ios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_singular_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_SPECIAL_START_LEVEL"

async def farm_special_aifa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_aifa"] = update.message.text.strip()
    await update.message.reply_text("🆔 *أدخل Custom User ID:*", parse_mode="Markdown")
    return "FARM_SPECIAL_SINGULAR_UID"

async def farm_special_singular_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["farm_singular_uid"] = update.message.text.strip()
    await update.message.reply_text("🔢 *مستوى البداية:*\nمثال: `1`", parse_mode="Markdown")
    return "FARM_SPECIAL_START_LEVEL"

async def farm_special_start_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sl = int(update.message.text.strip())
        context.user_data["farm_start"] = sl
        await update.message.reply_text(f"🔢 *مستوى النهاية:* (من {sl} إلى ?)\nمثال: `30`", parse_mode="Markdown")
        return "FARM_SPECIAL_END_LEVEL"
    except:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_SPECIAL_START_LEVEL"

async def farm_special_end_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        el = int(update.message.text.strip())
        sl = context.user_data["farm_start"]
        if el <= sl:
            await update.message.reply_text("❌ *يجب أن يكون أكبر من مستوى البداية*", parse_mode="Markdown")
            return "FARM_SPECIAL_END_LEVEL"
        context.user_data["farm_end"] = el
        
        # عرض جميع المستويات مع خيارات الوقت
        total_levels = el - sl + 1
        context.user_data["special_levels"] = list(range(sl, el + 1))
        context.user_data["special_times"] = {}
        
        await update.message.reply_text(
            f"⏰ *تحديد أوقات الضرب*\n\n"
            f"📊 عدد المستويات: {total_levels}\n"
            f"🎯 من {sl} → {el}\n\n"
            f"✨ *سيتم إعداد كل مستوى على حدة*\n"
            f"⚠️ *الآن اختر وقت الضرب للمستوى {sl}*",
            parse_mode="Markdown"
        )
        await ask_level_time(update, context, sl)
        return "FARM_SPECIAL_TIME"
        
    except:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_SPECIAL_END_LEVEL"

async def ask_level_time(update, context, level):
    """طلب وقت الضرب لمستوى محدد"""
    kb = [
        [InlineKeyboardButton("🕐 ساعات", callback_data=f"special_time_hours_{level}")],
        [InlineKeyboardButton("⏱️ دقائق", callback_data=f"special_time_minutes_{level}")],
        [InlineKeyboardButton("📅 أيام", callback_data=f"special_time_days_{level}")]
    ]
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(
        f"🎯 *المستوى {level}*\n\n"
        f"⏰ *بعد كم {('ساعة' if 'hours' in str(level) else 'من')} تريد ضرب هذا المستوى؟*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def farm_special_time_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار نوع الوقت للمستوى"""
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split("_")
    time_type = parts[2]  # hours, minutes, days
    level = int(parts[3])
    
    context.user_data["temp_level"] = level
    context.user_data["temp_time_type"] = time_type
    
    time_names = {"hours": "ساعات", "minutes": "دقائق", "days": "أيام"}
    await query.edit_message_text(
        f"🎯 *المستوى {level}*\n\n"
        f"⏰ *أدخل عدد {time_names[time_type]}:*\n"
        f"مثال: `5` (يعني بعد 5 {time_names[time_type]})",
        parse_mode="Markdown"
    )
    return "FARM_SPECIAL_TIME_VALUE"

async def farm_special_time_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدخال قيمة الوقت للمستوى"""
    try:
        value = int(update.message.text.strip())
        if value <= 0:
            await update.message.reply_text("❌ *أدخل رقماً أكبر من 0*", parse_mode="Markdown")
            return "FARM_SPECIAL_TIME_VALUE"
        
        level = context.user_data.get("temp_level")
        time_type = context.user_data.get("temp_time_type")
        
        # تحويل إلى ثواني
        if time_type == "hours":
            seconds = value * 3600
        elif time_type == "minutes":
            seconds = value * 60
        else:
            seconds = value * 86400
        
        context.user_data["special_times"][level] = seconds
        
        # الانتقال للمستوى التالي
        levels = context.user_data.get("special_levels", [])
        current_index = levels.index(level) if level in levels else -1
        
        if current_index + 1 < len(levels):
            next_level = levels[current_index + 1]
            await update.message.reply_text(f"✅ *تم ضبط المستوى {level}*\n⏰ سيتم الضرب بعد {value} {time_type}\n\n📊 *الآن قم بضبط المستوى {next_level}*", parse_mode="Markdown")
            await ask_level_time(update, context, next_level)
            return "FARM_SPECIAL_TIME"
        else:
            # تم الانتهاء من جميع المستويات
            await update.message.reply_text("✅ *تم ضبط جميع المستويات!*\n\n📋 *جارٍ إنشاء المزرعة...*", parse_mode="Markdown")
            await create_special_farm(update, context)
            return -1
            
    except ValueError:
        await update.message.reply_text("❌ *أدخل رقماً صحيحاً*", parse_mode="Markdown")
        return "FARM_SPECIAL_TIME_VALUE"

async def create_special_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء المزرعة بالوضع الخاص وجدولة المهام"""
    uid = update.effective_user.id
    task_name = f"SpecialFarm_{int(time.time())}_{uid}"
    
    # حفظ المزرعة في قاعدة البيانات
    c_main.execute("""INSERT INTO farm_tasks 
    (user_id, task_name, platform, game_id, game_name, start_level, end_level, total_days, mode, current_day, current_level, status, created_date, aifa, gaid, uid, af_uid, gps_adid, idfa, idfv)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (uid, task_name, context.user_data["farm_platform"], context.user_data["farm_game_id"], context.user_data["farm_game_name"],
     context.user_data["farm_start"], context.user_data["farm_end"], len(context.user_data["special_levels"]), "special",
     1, context.user_data["farm_start"], "running", datetime.now().isoformat(),
     context.user_data.get("farm_aifa", ""), context.user_data.get("farm_gaid", ""), context.user_data.get("farm_singular_uid", ""),
     context.user_data.get("farm_af_uid", ""), context.user_data.get("farm_gps", ""), context.user_data.get("farm_idfa", ""), context.user_data.get("farm_idfv", "")))
    conn_main.commit()
    
    task_id = c_main.execute("SELECT id FROM farm_tasks WHERE task_name = ?", (task_name,)).fetchone()[0]
    
    # جدولة المهام لكل مستوى
    current_time = time.time()
    for level, delay_seconds in context.user_data["special_times"].items():
        schedule_time = current_time + delay_seconds
        # تخزين المهمة المجدولة (سنستخدم asyncio.create_task مع asyncio.sleep)
        # للتطبيق العملي، سنخزن في قاموس وننشئ AsyncIO tasks
        job = asyncio.create_task(schedule_level_hit(update, context, task_id, level, schedule_time, context.user_data["farm_game_name"]))
        scheduled_jobs[f"{task_id}_{level}"] = job
    
    await update.message.reply_text(
        f"🌾 *تم إنشاء المزرعة بالوضع الخاص بنجاح!*\n\n"
        f"🆔 معرف المهمة: `{task_name}`\n"
        f"📊 عدد المستويات المجدولة: {len(context.user_data['special_times'])}\n"
        f"✨ *سيتم إرسال إشعار عند ضرب كل مستوى*",
        parse_mode="Markdown"
    )
    
    # تنظيف البيانات المؤقتة
    for key in ['special_levels', 'special_times', 'temp_level', 'temp_time_type']:
        context.user_data.pop(key, None)

async def schedule_level_hit(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: int, level: int, schedule_time: float, game_name: str):
    """جدولة ضرب مستوى محدد في وقت معين"""
    now = time.time()
    wait_time = schedule_time - now
    if wait_time > 0:
        await asyncio.sleep(wait_time)
    
    # تنفيذ ضرب المستوى
    uid = update.effective_user.id if update.effective_user else None
    if not uid:
        return
    
    task = c_main.execute("SELECT * FROM farm_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task or task['status'] != 'running':
        return
    
    proxy = get_proxy_for_user(uid)
    user_platform = get_user_platform(uid)
    
    success = False
    if task['platform'] == "af":
        game = c_main.execute("SELECT package, dev_key FROM games_af WHERE id = ?", (task['game_id'],)).fetchone()
        if game:
            event_name = f"level_{level}"
            if user_platform == "ios":
                status, resp = send_af(game['package'], game['dev_key'], None, task['af_uid'], event_name, None, proxy, "ios", task['idfa'], task['idfv'])
            else:
                status, resp = send_af(game['package'], game['dev_key'], task['gaid'], task['af_uid'], event_name, None, proxy, "android")
            success = status == 200
    
    elif task['platform'] == "adj":
        game = c_main.execute("SELECT app_token FROM games_adj WHERE id = ?", (task['game_id'],)).fetchone()
        if game:
            ev = c_main.execute("SELECT event_token FROM events_adj WHERE game_id = ? AND level_value = ?", (task['game_id'], level)).fetchone()
            if ev:
                status, resp = send_adj(game['app_token'], ev['event_token'], task['gps_adid'], proxy)
                success = status == 200
    
    elif task['platform'] == "singular":
        game = c_main.execute("SELECT package, app_key FROM games_singular WHERE id = ?", (task['game_id'],)).fetchone()
        if game:
            ev = c_main.execute("SELECT event_name FROM events_singular WHERE game_id = ?", (task['game_id'],)).fetchone()
            if ev:
                if user_platform == "ios":
                    status, resp = send_singular(ev['event_name'], None, task['uid'], game['package'], game['app_key'], level, proxy, "ios", task['idfa'], task['idfv'])
                else:
                    status, resp = send_singular(ev['event_name'], task['aifa'], task['uid'], game['package'], game['app_key'], level, proxy, "android")
                success = status == 200
    
    if success:
        # حساب المتبقي
        remaining = task['end_level'] - level
        await send_farm_notification(context, uid, task_id, level, remaining, task['end_level'], game_name)
        
        # التحقق إذا كان هذا آخر مستوى
        if level >= task['end_level']:
            c_main.execute("UPDATE farm_tasks SET status = 'completed' WHERE id = ?", (task_id,))
            conn_main.commit()
            try:
                await context.bot.send_message(uid, f"🎉 *اكتملت المزرعة!*\n🎮 {game_name}\n✅ تم ضرب جميع المستويات بنجاح!", parse_mode="Markdown")
            except:
                pass

# ==================================================================================
#                         دوال المدير لإضافة لعبة وحدث
# ==================================================================================
async def admin_add_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="add_game_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="add_game_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="add_game_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin")]
    ]
    await query.edit_message_text("🎮 *اختر نوع اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_GAME_TYPE"

async def add_game_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "af"
    await query.edit_message_text("📱 *أدخل اسم اللعبة (name)*\nمثال: `my_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "adj"
    await query.edit_message_text("📊 *أدخل اسم اللعبة (name)*\nمثال: `my_adj_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["game_type"] = "singular"
    await query.edit_message_text("🌟 *أدخل اسم اللعبة (name)*\nمثال: `my_singular_game`", parse_mode="Markdown")
    return "ADD_GAME_NAME"

async def add_game_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_name"] = update.message.text.strip()
    await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
    return "ADD_GAME_DISPLAY"

async def add_game_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_display"] = update.message.text.strip()
    await update.message.reply_text("📦 *أدخل Package Name*", parse_mode="Markdown")
    return "ADD_GAME_PACKAGE"

async def add_game_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_package"] = update.message.text.strip()
    gtype = context.user_data["game_type"]
    if gtype == "af":
        await update.message.reply_text("🔑 *أدخل Dev Key*", parse_mode="Markdown")
        return "ADD_GAME_KEY"
    elif gtype == "adj":
        await update.message.reply_text("🔑 *أدخل App Token*", parse_mode="Markdown")
        return "ADD_GAME_KEY"
    else:
        await update.message.reply_text("🔑 *أدخل App Key*", parse_mode="Markdown")
        return "ADD_GAME_KEY"

async def add_game_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["game_key"] = update.message.text.strip()
    await update.message.reply_text("🎨 *أدخل الإيموجي* (اختياري)", parse_mode="Markdown")
    return "ADD_GAME_EMOJI"

async def add_game_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip() or "🎮"
    gtype = context.user_data["game_type"]
    name = context.user_data["game_name"]
    display = context.user_data["game_display"]
    pkg = context.user_data["game_package"]
    key = context.user_data["game_key"]
    
    if gtype == "af":
        c_main.execute("INSERT INTO games_af (name, display_name, package, dev_key, emoji) VALUES (?, ?, ?, ?, ?)",
                       (name, display, pkg, key, emoji))
    elif gtype == "adj":
        c_main.execute("INSERT INTO games_adj (name, display_name, app_token, emoji) VALUES (?, ?, ?, ?)",
                       (name, display, key, emoji))
    else:
        c_main.execute("INSERT INTO games_singular (name, display_name, package, app_key, emoji) VALUES (?, ?, ?, ?, ?)",
                       (name, display, pkg, key, emoji))
    conn_main.commit()
    await update.message.reply_text(f"✅ *تم إضافة اللعبة*\n🎮 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_delete_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="del_game_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="del_game_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="del_game_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin")]
    ]
    await query.edit_message_text("🗑️ *اختر نوع اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_TYPE"

async def del_game_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"del_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_game")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_SELECT"

async def del_game_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"del_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_game")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_SELECT"

async def del_game_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"del_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_game")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_GAME_SELECT"

async def del_game_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    gtype = parts[1]
    game_id = int(parts[2])
    
    if gtype == "af":
        c_main.execute("DELETE FROM events_af WHERE game_id = ?", (game_id,))
        c_main.execute("DELETE FROM games_af WHERE id = ?", (game_id,))
    elif gtype == "adj":
        c_main.execute("DELETE FROM events_adj WHERE game_id = ?", (game_id,))
        c_main.execute("DELETE FROM games_adj WHERE id = ?", (game_id,))
    else:
        c_main.execute("DELETE FROM events_singular WHERE game_id = ?", (game_id,))
        c_main.execute("DELETE FROM games_singular WHERE id = ?", (game_id,))
    conn_main.commit()
    await query.edit_message_text("✅ *تم حذف اللعبة*", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="add_event_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="add_event_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="add_event_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin")]
    ]
    await query.edit_message_text("🎯 *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_TYPE"

async def add_event_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"ev_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_add_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_GAME"

async def add_event_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"ev_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_add_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_GAME"

async def add_event_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"ev_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_add_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "ADD_EVENT_GAME"

async def add_event_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    try:
        context.user_data["event_game_type"] = parts[1]
        context.user_data["event_game_id"] = int(parts[2])
    except (IndexError, ValueError):
        await query.edit_message_text("❌ خطأ في بيانات اللعبة", parse_mode="Markdown")
        return -1
    await query.edit_message_text("📝 *أدخل اسم الحدث (event_name)*", parse_mode="Markdown")
    return "ADD_EVENT_NAME"

async def add_event_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["event_name"] = update.message.text.strip()
    gtype = context.user_data["event_game_type"]
    if gtype == "adj":
        await update.message.reply_text("🔑 *أدخل Event Token*", parse_mode="Markdown")
        return "ADD_EVENT_TOKEN"
    else:
        await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
        return "ADD_EVENT_DISPLAY"

async def add_event_display(update: Update, context: ContextTypes.DEFAULT_TYPE):
    display = update.message.text.strip()
    gtype = context.user_data["event_game_type"]
    game_id = context.user_data["event_game_id"]
    event_name = context.user_data["event_name"]
    
    if gtype == "af":
        c_main.execute("INSERT INTO events_af (game_id, event_name, display_name, event_type, is_purchase) VALUES (?, ?, ?, ?, ?)",
                       (game_id, event_name, display, "custom", 0))
    else:
        c_main.execute("INSERT INTO events_singular (game_id, event_name, display_name, event_type) VALUES (?, ?, ?, ?)",
                       (game_id, event_name, display, "custom"))
    conn_main.commit()
    cache_clear(f"af_events_{game_id}")
    cache_clear(f"singular_events_{game_id}")
    await update.message.reply_text(f"✅ *تم إضافة الحدث*\n📝 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def add_event_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    context.user_data["event_token"] = token
    await update.message.reply_text("📝 *أدخل الاسم الظاهر*", parse_mode="Markdown")
    return "ADD_EVENT_DISPLAY_ADJ"

async def add_event_display_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    display = update.message.text.strip()
    game_id = context.user_data["event_game_id"]
    event_name = context.user_data["event_name"]
    token = context.user_data["event_token"]
    
    c_main.execute("INSERT INTO events_adj (game_id, event_name, event_token, display_name, level_value) VALUES (?, ?, ?, ?, ?)",
                   (game_id, event_name, token, display, 0))
    conn_main.commit()
    cache_clear(f"adj_events_{game_id}")
    await update.message.reply_text(f"✅ *تم إضافة الحدث*\n📝 {display}", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]]
    await update.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

async def admin_delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ غير مصرح", parse_mode="Markdown")
        return -1
    kb = [
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="del_event_af")],
        [InlineKeyboardButton("📊 Adjust", callback_data="del_event_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="del_event_singular")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin")]
    ]
    await query.edit_message_text("🗑️ *اختر نوع الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_TYPE"

async def del_event_af(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_af()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"dev_af_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_GAME"

async def del_event_adj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_adj()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"dev_adj_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_GAME"

async def del_event_singular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    games = get_all_games_singular()
    if not games:
        await query.edit_message_text("❌ *لا توجد ألعاب*", parse_mode="Markdown")
        return -1
    kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"dev_singular_{g[0]}")] for g in games]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎮 *اختر اللعبة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_GAME"

async def del_event_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    gtype = parts[1]
    try:
        game_id = int(parts[2])
    except ValueError:
        await query.edit_message_text("❌ خطأ في معرف اللعبة", parse_mode="Markdown")
        return -1
    
    if gtype == "af":
        events = c_main.execute("SELECT id, display_name FROM events_af WHERE game_id = ?", (game_id,)).fetchall()
    elif gtype == "adj":
        events = c_main.execute("SELECT id, display_name FROM events_adj WHERE game_id = ?", (game_id,)).fetchall()
    else:
        events = c_main.execute("SELECT id, display_name FROM events_singular WHERE game_id = ?", (game_id,)).fetchall()
    
    if not events:
        await query.edit_message_text("❌ *لا توجد أحداث*", parse_mode="Markdown")
        return -1
    
        kb = [[InlineKeyboardButton(ev[1], callback_data=f"delev_{gtype}_{ev[0]}")] for ev in events]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_delete_event")])
    await query.edit_message_text("🎯 *اختر الحدث*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "DEL_EVENT_SELECT"

async def del_event_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ خطأ في البيانات", parse_mode="Markdown")
        return -1
    gtype = parts[1]
    try:
        event_id = int(parts[2])
    except ValueError:
        await query.edit_message_text("❌ خطأ في معرف الحدث", parse_mode="Markdown")
        return -1
    
    if gtype == "af":
        c_main.execute("DELETE FROM events_af WHERE id = ?", (event_id,))
    elif gtype == "adj":
        c_main.execute("DELETE FROM events_adj WHERE id = ?", (event_id,))
    else:
        c_main.execute("DELETE FROM events_singular WHERE id = ?", (event_id,))
    conn_main.commit()
    cache_clear()
    await query.edit_message_text("✅ *تم حذف الحدث*", parse_mode="Markdown")
    kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]]
    await query.message.reply_text("العودة:", reply_markup=InlineKeyboardMarkup(kb))
    return -1

# ==================================================================================
#                             التشغيل الرئيسي
# ==================================================================================
# ==================================================================================
#                               دوال البروكسي الأساسية
# ==================================================================================

async def proxy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    pinfo = get_proxy_info(uid)
    status = "❌ *لا يوجد بروكسي*" if not pinfo else f"✅ *البروكسي الحالي:*\n📡 النوع: `{pinfo[0]}`\n🌐 {pinfo[1]}:{pinfo[2]}"
    kb = [
        [InlineKeyboardButton("🔧 إضافة بروكسي", callback_data="proxy_add")],
        [InlineKeyboardButton("🗑️ حذف البروكسي", callback_data="proxy_del")],
        [InlineKeyboardButton("📡 اختبار البروكسي", callback_data="proxy_test")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ]
    await query.edit_message_text(
        f"🔧 *إعدادات البروكسي*\n\n{status}\n\n"
        f"✨ *اختر إجراء:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "PROXY_MAIN"

async def proxy_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار نوع البروكسي"""
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("🔒 HTTP / HTTPS", callback_data="proxy_type_http")],
        [InlineKeyboardButton("🔓 SOCKS5", callback_data="proxy_type_socks5")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="proxy_settings")]
    ]
    await query.edit_message_text(
        "🔧 *إضافة بروكسي جديد*\n\n"
        "✨ *اختر نوع البروكسي:*\n\n"
        "• 🔒 HTTP/HTTPS: للبروكسيات العادية\n"
        "• 🔓 SOCKS5: للبروكسيات الآمنة",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "PROXY_TYPE"

async def proxy_type_http(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["proxy_type"] = "http"
    await query.edit_message_text(
        "🔒 *بروكسي HTTP/HTTPS*\n\n"
        "📝 *أدخل IP والمنفذ:*\n"
        "مثال: `192.168.1.100:8080`",
        parse_mode="Markdown"
    )
    return "PROXY_IP_PORT"

async def proxy_type_socks5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["proxy_type"] = "socks5"
    await query.edit_message_text(
        "🔓 *بروكسي SOCKS5*\n\n"
        "📝 *أدخل IP والمنفذ:*\n"
        "مثال: `192.168.1.100:1080`",
        parse_mode="Markdown"
    )
    return "PROXY_IP_PORT"

async def proxy_ip_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ip_port = update.message.text.strip()
    try:
        if ":" not in ip_port:
            await update.message.reply_text("❌ *صيغة خاطئة*\nاستخدم: `ip:port`", parse_mode="Markdown")
            return "PROXY_IP_PORT"
        
        host, port = ip_port.split(":", 1)
        port = int(port)
        
        context.user_data["proxy_host"] = host
        context.user_data["proxy_port"] = port
        
        kb = [
            [InlineKeyboardButton("✅ لا، بدون مصادقة", callback_data="proxy_no_auth")],
            [InlineKeyboardButton("🔐 نعم، إضافة مصادقة", callback_data="proxy_need_auth")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="proxy_add")]
        ]
        await update.message.reply_text(
            f"✅ *تم تعيين:* `{host}:{port}`\n\n"
            f"🔐 *هل تحتاج المصادقة (Username/Password)؟*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return "PROXY_AUTH"
        
    except ValueError:
        await update.message.reply_text("❌ *المنفذ يجب أن يكون رقماً*", parse_mode="Markdown")
        return "PROXY_IP_PORT"
    except Exception as e:
        await update.message.reply_text(f"❌ *خطأ:* `{e}`", parse_mode="Markdown")
        return "PROXY_IP_PORT"

async def proxy_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف البروكسي"""
    query = update.callback_query
    await query.answer()
    delete_proxy(query.from_user.id)
    await query.edit_message_text("✅ *تم حذف البروكسي بنجاح*", parse_mode="Markdown")
    await asyncio.sleep(1)
    await main_menu(update, context)
    return -1

async def proxy_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختبار البروكسي الحالي"""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    proxy_info = get_proxy_info(uid)
    
    if not proxy_info:
        await query.edit_message_text("❌ *لا يوجد بروكسي*\n\nيرجى إضافة بروكسي أولاً", parse_mode="Markdown")
        return -1
    
    proxy_type, host, port, user, pwd = proxy_info
    
    # بناء البروكسي للاختبار
    if user and pwd:
        auth = f"{user}:{pwd}@"
    else:
        auth = ""
    
    if proxy_type == "socks5":
        proxy_url = f"socks5://{auth}{host}:{port}"
        proxies = {"socks5": proxy_url, "http": proxy_url, "https": proxy_url}
    else:
        proxy_url = f"http://{auth}{host}:{port}"
        proxies = {"http": proxy_url, "https": proxy_url}
    
    await query.edit_message_text("📡 *جاري اختبار البروكسي...*", parse_mode="Markdown")
    
    try:
        test_url = 'https://api.ipify.org?format=json'
        response = requests.get(test_url, proxies=proxies, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            proxy_ip = data.get('ip', 'Unknown')
            
            await query.message.reply_text(
                f"✅ *البروكسي يعمل*\n\n"
                f"📡 *النوع:* `{proxy_type.upper()}`\n"
                f"🌐 *السيرفر:* `{host}:{port}`\n"
                f"🌍 *IP البروكسي:* `{proxy_ip}`",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(
                f"❌ *البروكسي لا يعمل*\n\n"
                f"📡 *النوع:* `{proxy_type.upper()}`\n"
                f"🌐 *السيرفر:* `{host}:{port}`",
                parse_mode="Markdown"
            )
    except Exception:
        await query.message.reply_text(
            f"❌ *البروكسي لا يعمل*\n\n"
            f"📡 *النوع:* `{proxy_type.upper()}`\n"
            f"🌐 *السيرفر:* `{host}:{port}`",
            parse_mode="Markdown"
        )
    
    await asyncio.sleep(2)
    await proxy_settings(update, context)
    return -1
   

# ==================================================================================
#                         جدولة العمليات (الجديدة)
# ==================================================================================

# جدول لتتبع مهام asyncio النشطة: {group_id: asyncio.Task}
sched_active_tasks: Dict[int, "asyncio.Task"] = {}
sched_tasks_lock = threading.Lock()

# إنشاء جدول جلسات الجدولة في قاعدة البيانات
c_main.execute('''CREATE TABLE IF NOT EXISTS sched_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    platform TEXT,
    game_id INTEGER,
    game_name TEXT,
    game_pkg TEXT,
    game_key TEXT,
    events_order TEXT,
    interval_minutes INTEGER,
    gaid TEXT,
    af_uid TEXT,
    status TEXT DEFAULT 'active',
    created_date TEXT,
    next_run TEXT
)''')
c_main.execute("CREATE INDEX IF NOT EXISTS idx_sched_groups_user ON sched_groups(user_id)")
c_main.execute("CREATE INDEX IF NOT EXISTS idx_sched_groups_status ON sched_groups(status)")
conn_main.commit()

def get_sched_groups(user_id: int):
    return c_main.execute(
        "SELECT id, platform, game_name, events_order, interval_minutes, gaid, af_uid, status, next_run FROM sched_groups WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()

# ==================== حلقة التنفيذ الرئيسية لكل مجموعة ====================
async def run_sched_group_loop(bot, group_id: int, user_id: int):
    """يرسل أحداث المجموعة بالترتيب مع فاصل زمني وعداد تنازلي بين كل حدث والتالي"""
    loop = asyncio.get_event_loop()

    # جلب بيانات المجموعة من DB
    g = c_main.execute(
        "SELECT platform, game_name, game_pkg, game_key, events_order, interval_minutes, gaid, af_uid, status, game_id FROM sched_groups WHERE id = ?",
        (group_id,)
    ).fetchone()
    if not g or g[8] != 'active':
        with sched_tasks_lock:
            sched_active_tasks.pop(group_id, None)
        return

    platform, game_name, game_pkg, game_key, events_order_raw, interval, gaid, af_uid, _, game_id = g
    try:
        events = json.loads(events_order_raw)
    except Exception:
        with sched_tasks_lock:
            sched_active_tasks.pop(group_id, None)
        return

    # اكتشاف الفورمات: مخصص (list of dicts) أم قديم (list of [id, name])
    is_custom = events and isinstance(events[0], dict) and "level" in events[0]
    proxy = get_proxy_for_user(user_id)
    interval_seconds = interval * 60  # 0 = فوري، -1 = مخصص لكل لفل، >0 = موحّد

    # ===== دالة مساعدة: انتظار مع عداد تنازلي =====
    async def wait_with_countdown(wait_min: float, label: str) -> bool:
        """ينتظر wait_min دقيقة مع عداد. يُرجع False إذا تم الإيقاف."""
        if wait_min <= 0:
            await asyncio.sleep(0.5)
            return True
        wait_sec = wait_min * 60
        update_every = 10 if wait_sec <= 120 else 30
        if wait_min < 60:
            interval_label = f"{int(wait_min)} دقيقة" if wait_min == int(wait_min) else f"{wait_min:.1f} دقيقة"
        else:
            h = wait_min / 60
            interval_label = f"{int(h)} ساعة" if h == int(h) else f"{h:.1f} ساعة"
        try:
            cdmsg = await bot.send_message(
                chat_id=user_id,
                text=f"⏳ *{label}*\nيُرسل خلال {interval_label}...",
                parse_mode="Markdown"
            )
        except Exception:
            cdmsg = None
        elapsed = 0
        while elapsed < wait_sec:
            await asyncio.sleep(update_every)
            elapsed += update_every
            status_row = c_main.execute("SELECT status FROM sched_groups WHERE id = ?", (group_id,)).fetchone()
            if not status_row or status_row[0] != 'active':
                if cdmsg:
                    try: await cdmsg.edit_text("⏹ *تم إيقاف الجدولة*", parse_mode="Markdown")
                    except Exception: pass
                with sched_tasks_lock:
                    sched_active_tasks.pop(group_id, None)
                return False
            remaining = max(0, wait_sec - elapsed)
            if remaining == 0:
                break
            if cdmsg:
                rm = int(remaining // 60)
                rs = int(remaining % 60)
                try:
                    await cdmsg.edit_text(
                        f"⏳ *{label}*\nيُرسل خلال {rm}د {rs:02d}ث",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        if cdmsg:
            try: await cdmsg.delete()
            except Exception: pass
        return True

    # ===== دالة مساعدة: إرسال الحدث =====
    async def send_event(ev_label: str, ev_id_or_level) -> tuple:
        """يرسل الحدث حسب المنصة. يُرجع (status_code, resp)."""
        sc, rs = 0, ""
        try:
            if is_custom:
                level_num = ev_id_or_level
                if platform == "adj":
                    ev_row = c_main.execute(
                        "SELECT event_token FROM events_adj WHERE game_id = ? ORDER BY ABS(COALESCE(level_value,0) - ?) LIMIT 1",
                        (game_id, level_num)
                    ).fetchone()
                    if not ev_row:
                        ev_row = c_main.execute("SELECT event_token FROM events_adj WHERE game_id = ? LIMIT 1", (game_id,)).fetchone()
                    if ev_row:
                        sc, rs = await loop.run_in_executor(None, lambda t=ev_row[0]: send_adj(game_key, t, gaid, proxy))
                elif platform == "singular":
                    ev_row = c_main.execute(
                        "SELECT event_name FROM events_singular WHERE game_id = ? LIMIT 1", (game_id,)
                    ).fetchone()
                    if ev_row:
                        custom_name = re.sub(r'\d+', str(level_num), ev_row[0]) if re.search(r'\d+', ev_row[0]) else f"level_{level_num}"
                        sc, rs = await loop.run_in_executor(None, lambda e=custom_name: send_singular(e, gaid, af_uid, game_pkg, game_key, proxy=proxy))
                else:  # af
                    ev_row = c_main.execute(
                        "SELECT event_name FROM events_af WHERE game_id = ? AND event_type='level' LIMIT 1", (game_id,)
                    ).fetchone()
                    if not ev_row:
                        ev_row = c_main.execute("SELECT event_name FROM events_af WHERE game_id = ? LIMIT 1", (game_id,)).fetchone()
                    if ev_row:
                        custom_name = re.sub(r'\d+', str(level_num), ev_row[0]) if re.search(r'\d+', ev_row[0]) else f"af_level_{level_num}_achieved"
                        sc, rs = await loop.run_in_executor(None, lambda e=custom_name: send_af(game_pkg, game_key, gaid, af_uid, e, proxy=proxy))
            else:
                ev_id = ev_id_or_level
                if platform == "adj":
                    ev_row = c_main.execute("SELECT event_token FROM events_adj WHERE id = ?", (ev_id,)).fetchone()
                    if ev_row:
                        sc, rs = await loop.run_in_executor(None, lambda t=ev_row[0]: send_adj(game_key, t, gaid, proxy))
                elif platform == "singular":
                    ev_row = c_main.execute("SELECT event_name FROM events_singular WHERE id = ?", (ev_id,)).fetchone()
                    if ev_row:
                        sc, rs = await loop.run_in_executor(None, lambda e=ev_row[0]: send_singular(e, gaid, af_uid, game_pkg, game_key, proxy=proxy))
                else:
                    ev_row = c_main.execute("SELECT event_name FROM events_af WHERE id = ?", (ev_id,)).fetchone()
                    if ev_row:
                        sc, rs = await loop.run_in_executor(None, lambda e=ev_row[0]: send_af(game_pkg, game_key, gaid, af_uid, e, proxy=proxy))
        except Exception as ex:
            sc, rs = 0, str(ex)
        return sc, rs

    # ===== إرسال الأحداث بالترتيب =====
    for ev_index, entry in enumerate(events):
        # تحقق إذا تم الإيقاف
        status_row = c_main.execute("SELECT status FROM sched_groups WHERE id = ?", (group_id,)).fetchone()
        if not status_row or status_row[0] != 'active':
            with sched_tasks_lock:
                sched_active_tasks.pop(group_id, None)
            return

        if is_custom:
            level_num = entry["level"]
            ev_wait_min = entry["interval"]
            ev_label = f"LV{level_num}"
            ev_key = level_num
        else:
            ev_id, ev_name = entry[0], entry[1]
            ev_wait_min = 0 if interval_seconds == 0 else (interval if ev_index > 0 else 0)
            ev_label = ev_name
            ev_key = ev_id

        # --- انتظار الفاصل الزمني قبل الإرسال ---
        if ev_wait_min > 0:
            ok = await wait_with_countdown(ev_wait_min, f"اللفل التالي: {ev_label}")
            if not ok:
                return
        elif not is_custom and ev_index > 0 and interval_seconds > 0:
            ok = await wait_with_countdown(interval, ev_label)
            if not ok:
                return

        # تحقق مجدداً بعد الانتظار
        status_row = c_main.execute("SELECT status FROM sched_groups WHERE id = ?", (group_id,)).fetchone()
        if not status_row or status_row[0] != 'active':
            with sched_tasks_lock:
                sched_active_tasks.pop(group_id, None)
            return

        # --- إرسال الحدث ---
        status_code, resp = await send_event(ev_label, ev_key)

        # --- إشعار بنتيجة الإرسال ---
        result_emoji = "✅" if status_code == 200 else "❌"
        remaining_count = len(events) - ev_index - 1
        remaining_text = f"\n⏭ *متبقي:* `{remaining_count} لفل`" if remaining_count > 0 else ""
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"{result_emoji} *إرسال تلقائي*\n\n"
                    f"🎮 *اللعبة:* `{game_name}`\n"
                    f"🎯 *الحدث:* `{ev_label}`\n"
                    f"🔹 *المنصة:* `{platform.upper()}`\n"
                    f"📱 *GAID:* `{gaid}`\n"
                    f"🔑 *AF UID:* `{af_uid}`\n"
                    f"📊 *الحالة:* `HTTP {status_code}`\n"
                    f"🕐 *الوقت:* `{datetime.now().strftime('%H:%M:%S')}`"
                    f"{remaining_text}"
                ),
                parse_mode="Markdown"
            )
            increment_user_requests(user_id)
        except Exception:
            pass

        # وضع فوري (قديم): فاصل 0.5ث بين الأحداث
        if not is_custom and interval_seconds == 0 and ev_index < len(events) - 1:
            await asyncio.sleep(0.5)

    # ===== اكتمال جميع الأحداث: إشعار وإيقاف تلقائي =====
    try:
        if is_custom:
            events_summary = "\n".join([f"{i+1}. LV{e['level']}" for i, e in enumerate(events)])
        else:
            events_summary = "\n".join([f"{i+1}. {e[1]}" for i, e in enumerate(events)])
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 *تم اكتمال جميع المهام!*\n\n"
                f"🎮 *اللعبة:* `{game_name}`\n"
                f"🔹 *المنصة:* `{platform.upper()}`\n"
                f"📋 *الأحداث المنفذة:*\n{events_summary}\n"
                f"🕐 *وقت الاكتمال:* `{datetime.now().strftime('%H:%M:%S')}`\n\n"
                f"⏹ تم إيقاف المجموعة تلقائياً."
            ),
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # إيقاف المجموعة تلقائياً
    c_main.execute("UPDATE sched_groups SET status = 'stopped' WHERE id = ?", (group_id,))
    conn_main.commit()
    with sched_tasks_lock:
        sched_active_tasks.pop(group_id, None)
def start_sched_task(bot, group_id: int, user_id: int):
    """يُنشئ asyncio.Task للمجموعة ويسجلها"""
    with sched_tasks_lock:
        if group_id in sched_active_tasks and not sched_active_tasks[group_id].done():
            return  # تعمل بالفعل
        task = asyncio.create_task(run_sched_group_loop(bot, group_id, user_id))
        sched_active_tasks[group_id] = task

def stop_sched_task(group_id: int):
    """يوقف Task المجموعة"""
    with sched_tasks_lock:
        task = sched_active_tasks.pop(group_id, None)
        if task and not task.done():
            task.cancel()

# ==================== معالجات Telegram ====================
async def sched_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("➕ مجموعة جديدة", callback_data="sched_new")],
        [InlineKeyboardButton("📋 مجموعاتي", callback_data="sched_my_groups")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")],
    ]
    await query.edit_message_text(
        "⏰ *جدولة العمليات*\n\nاختر خيار من القائمة أدناه:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_MAIN"

async def sched_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["sched"] = {}
    kb = [
        [InlineKeyboardButton("📊 Adjust", callback_data="sched_platform_adj")],
        [InlineKeyboardButton("🌟 Singular", callback_data="sched_platform_singular")],
        [InlineKeyboardButton("📱 AppsFlyer", callback_data="sched_platform_af")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sched_menu")],
    ]
    await query.edit_message_text(
        "⏰ *مجموعة جديدة*\n\n🔹 اختر المنصة:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_PLATFORM"

async def sched_platform_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data.replace("sched_platform_", "")
    context.user_data["sched"]["platform"] = platform

    if platform == "adj":
        games = get_all_games_adj()
        kb = [[InlineKeyboardButton(f"{g[4]} {g[2]}", callback_data=f"sched_game_{g[0]}")] for g in games]
    elif platform == "singular":
        games = get_all_games_singular()
        kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"sched_game_{g[0]}")] for g in games]
    else:
        games = get_all_games_af()
        kb = [[InlineKeyboardButton(f"{g[5]} {g[2]}", callback_data=f"sched_game_{g[0]}")] for g in games]

    if not games:
        await query.edit_message_text("❌ لا توجد ألعاب في هذه المنصة", parse_mode="Markdown")
        return "SCHED_PLATFORM"

    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="sched_new")])
    await query.edit_message_text(
        "🎮 *اختر اللعبة:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_GAME"

async def sched_game_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_id = int(query.data.replace("sched_game_", ""))
    platform = context.user_data["sched"]["platform"]

    if platform == "adj":
        g = c_main.execute("SELECT id, name, display_name, app_token, emoji FROM games_adj WHERE id = ?", (game_id,)).fetchone()
        if not g:
            await query.edit_message_text("❌ لعبة غير موجودة", parse_mode="Markdown")
            return "SCHED_GAME"
        context.user_data["sched"]["game_id"] = g[0]
        context.user_data["sched"]["game_name"] = g[2]
        context.user_data["sched"]["game_pkg"] = ""
        context.user_data["sched"]["game_key"] = g[3]
        events = get_adj_events(game_id)
        ev_list = [(e[0], e[3]) for e in events]
    elif platform == "singular":
        g = c_main.execute("SELECT id, name, display_name, package, app_key, emoji FROM games_singular WHERE id = ?", (game_id,)).fetchone()
        if not g:
            await query.edit_message_text("❌ لعبة غير موجودة", parse_mode="Markdown")
            return "SCHED_GAME"
        context.user_data["sched"]["game_id"] = g[0]
        context.user_data["sched"]["game_name"] = g[2]
        context.user_data["sched"]["game_pkg"] = g[3]
        context.user_data["sched"]["game_key"] = g[4]
        events = get_singular_events(game_id)
        ev_list = [(e[0], e[2]) for e in events]
    else:
        g = c_main.execute("SELECT id, name, display_name, package, dev_key, emoji FROM games_af WHERE id = ?", (game_id,)).fetchone()
        if not g:
            await query.edit_message_text("❌ لعبة غير موجودة", parse_mode="Markdown")
            return "SCHED_GAME"
        context.user_data["sched"]["game_id"] = g[0]
        context.user_data["sched"]["game_name"] = g[2]
        context.user_data["sched"]["game_pkg"] = g[3]
        context.user_data["sched"]["game_key"] = g[4]
        all_ev = get_af_events(game_id)
        all_ev_pur = get_af_events(game_id, purchase_only=True)
        events = list(all_ev) + list(all_ev_pur)
        ev_list = [(e[0], e[2]) for e in events]

    if not ev_list:
        await query.edit_message_text("❌ لا توجد أحداث لهذه اللعبة", parse_mode="Markdown")
        return "SCHED_GAME"

    context.user_data["sched"]["all_events"] = ev_list
    context.user_data["sched"]["selected_events"] = []
    return await sched_ask_levels(update, context)

def parse_level_time(time_str: str) -> float:
    """تحويل نص الوقت (1h, 0.5h, 30m) إلى دقائق"""
    s = time_str.strip().lower()
    if s in ('0', '0h', '0m'):
        return 0.0
    if s.endswith('h'):
        return float(s[:-1]) * 60
    if s.endswith('m'):
        return float(s[:-1])
    return float(s)

async def sched_ask_levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sched = context.user_data["sched"]
    game_name = sched["game_name"]
    platform = sched["platform"]
    text = (
        f"🎮 *{game_name}* | *{platform.upper()}*\n\n"
        f"أرسل اللفلات مع الفاصل الزمني — كل سطر لفل واحد:\n\n"
        f"`LV15/1h`\n`LV17/2h`\n`LV18/0.5h`\n`LV19/0.25h`\n\n"
        f"📌 صيغ الوقت: `1h` ساعة · `0.5h` نصف ساعة · `30m` دقيقة · `0` فوري"
    )
    try:
        await query.edit_message_text(text, parse_mode="Markdown")
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown")
    return "SCHED_LEVELS"

async def sched_levels_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    sched = context.user_data["sched"]
    entries = []
    errors = []
    for i, line in enumerate(text.split('\n'), 1):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^[Ll][Vv](\d+)/(.+)$', line)
        if not m:
            errors.append(f"سطر {i}: `{line}` — صيغة خاطئة")
            continue
        level_num = int(m.group(1))
        try:
            interval_min = parse_level_time(m.group(2))
        except ValueError:
            errors.append(f"سطر {i}: وقت غير صحيح `{m.group(2)}`")
            continue
        entries.append({"level": level_num, "interval": interval_min})
    if errors:
        await update.message.reply_text(
            "❌ *أخطاء في الصيغة:*\n" + "\n".join(errors) + "\n\nأعد الإرسال.",
            parse_mode="Markdown"
        )
        return "SCHED_LEVELS"
    if not entries:
        await update.message.reply_text("❌ لم يتم إدخال أي لفل. أعد الإرسال.", parse_mode="Markdown")
        return "SCHED_LEVELS"
    sched["custom_levels"] = entries
    sched["interval"] = -1
    await update.message.reply_text("📱 *أدخل GAID:*\n\nمثال: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`", parse_mode="Markdown")
    return "SCHED_GAID"

async def sched_show_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sched = context.user_data["sched"]
    ev_list = sched["all_events"]
    selected = sched.get("selected_events", [])
    selected_ids = [e[0] for e in selected]

    kb = []
    for ev_id, ev_name in ev_list:
        if ev_id in selected_ids:
            order_num = selected_ids.index(ev_id) + 1
            btn_text = f"✅ [{order_num}] {ev_name}"
        else:
            btn_text = f"⬜ {ev_name}"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"sched_ev_{ev_id}")])

    if selected:
        kb.append([InlineKeyboardButton("💾 حفظ", callback_data="sched_save_events")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="sched_new")])

    selected_text = ""
    if selected:
        selected_text = "\n\n*الأحداث المختارة:*\n" + "\n".join([f"{i+1}. {e[1]}" for i, e in enumerate(selected)])

    await query.edit_message_text(
        f"🎯 *اختر الأحداث بالترتيب:*{selected_text}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_EVENTS"

async def sched_event_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ev_id = int(query.data.replace("sched_ev_", ""))
    sched = context.user_data["sched"]
    selected = sched.get("selected_events", [])
    selected_ids = [e[0] for e in selected]

    if ev_id in selected_ids:
        sched["selected_events"] = [e for e in selected if e[0] != ev_id]
    else:
        ev_name = next((e[1] for e in sched["all_events"] if e[0] == ev_id), str(ev_id))
        sched["selected_events"].append((ev_id, ev_name))

    return await sched_show_events(update, context)

async def sched_save_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sched = context.user_data["sched"]
    if not sched.get("selected_events"):
        await query.answer("⚠️ اختر حدثاً واحداً على الأقل", show_alert=True)
        return "SCHED_EVENTS"

    kb = [
        [InlineKeyboardButton("🚀 فوري (بدون فاصل)", callback_data="sched_interval_0")],
        [InlineKeyboardButton("⚡ 1 دقيقة", callback_data="sched_interval_1")],
        [InlineKeyboardButton("⏱ 15 دقيقة", callback_data="sched_interval_15")],
        [InlineKeyboardButton("⏱ 25 دقيقة", callback_data="sched_interval_25")],
        [InlineKeyboardButton("⏱ 1 ساعة", callback_data="sched_interval_60")],
        [InlineKeyboardButton("⏱ 2 ساعة", callback_data="sched_interval_120")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sched_back_events")],
    ]
    await query.edit_message_text(
        "⏰ *اختر الفاصل الزمني بين كل دورة:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_INTERVAL"

async def sched_interval_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    minutes = int(query.data.replace("sched_interval_", ""))
    context.user_data["sched"]["interval"] = minutes
    await query.edit_message_text(
        "📱 *أدخل GAID:*\n\nمثال: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`",
        parse_mode="Markdown"
    )
    return "SCHED_GAID"

async def sched_gaid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gaid = update.message.text.strip()
    context.user_data["sched"]["gaid"] = gaid
    await update.message.reply_text("🔑 *أدخل AF UID:*", parse_mode="Markdown")
    return "SCHED_AFUID"

async def sched_afuid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    af_uid = update.message.text.strip()
    context.user_data["sched"]["af_uid"] = af_uid
    sched = context.user_data["sched"]

    platform = sched["platform"]
    game_name = sched["game_name"]
    gaid = sched["gaid"]

    if sched.get("custom_levels"):
        entries = sched["custom_levels"]
        def fmt_interval(m):
            if m == 0:
                return "فوري"
            if m < 60:
                return f"{int(m)}د"
            return f"{m/60:.1f}س".rstrip('0').rstrip('.')+"س" if '.' in f"{m/60:.1f}" else f"{int(m//60)}س"
        events_text = "\n".join([f"{i+1}. LV{e['level']} ← بعد {fmt_interval(e['interval'])}" for i, e in enumerate(entries)])
        interval_text = "مخصص لكل لفل"
    else:
        events = sched["selected_events"]
        interval = sched["interval"]
        if interval == 0:
            interval_text = "فوري (بدون فاصل)"
        elif interval < 60:
            interval_text = f"{interval} دقيقة"
        else:
            interval_text = f"{interval // 60} ساعة"
        events_text = "\n".join([f"{i+1}. {e[1]}" for i, e in enumerate(events)])

    kb = [
        [InlineKeyboardButton("✅ تأكيد وتشغيل", callback_data="sched_confirm")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="sched_menu")],
    ]
    await update.message.reply_text(
        f"📋 *تفاصيل الخطة:*\n\n"
        f"🔹 *المنصة:* `{platform.upper()}`\n"
        f"🎮 *اللعبة:* `{game_name}`\n"
        f"🎯 *اللفلات بالترتيب:*\n{events_text}\n"
        f"⏰ *الفاصل الزمني:* `{interval_text}`\n"
        f"📱 *GAID:* `{gaid}`\n"
        f"🔑 *AF UID:* `{af_uid}`",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_CONFIRM"

async def sched_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    sched = context.user_data["sched"]

    platform = sched["platform"]
    game_id = sched["game_id"]
    game_name = sched["game_name"]
    game_pkg = sched["game_pkg"]
    game_key = sched["game_key"]
    gaid = sched["gaid"]
    af_uid = sched["af_uid"]

    if sched.get("custom_levels"):
        events_order = json.dumps(sched["custom_levels"], ensure_ascii=False)
        interval = -1
    else:
        events = sched["selected_events"]
        interval = sched["interval"]
        events_order = json.dumps([(e[0], e[1]) for e in events], ensure_ascii=False)
    now = datetime.now().isoformat()

    c_main.execute(
        "INSERT INTO sched_groups (user_id, platform, game_id, game_name, game_pkg, game_key, events_order, interval_minutes, gaid, af_uid, status, created_date, next_run) VALUES (?,?,?,?,?,?,?,?,?,?,'active',?,?)",
        (uid, platform, game_id, game_name, game_pkg, game_key, events_order, interval, gaid, af_uid, now, now)
    )
    conn_main.commit()
    group_id = c_main.execute("SELECT last_insert_rowid()").fetchone()[0]

    await query.edit_message_text(
        f"✅ *تم تفعيل الجدولة!*\n\n"
        f"🆔 معرف المجموعة: `{group_id}`\n"
        f"🚀 يبدأ الإرسال الآن...",
        parse_mode="Markdown"
    )

    # ابدأ التنفيذ فوراً
    start_sched_task(context.bot, group_id, uid)
    return -1

async def sched_my_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    groups = get_sched_groups(uid)

    if not groups:
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="sched_menu")]]
        await query.edit_message_text("📋 *لا توجد مجموعات محفوظة*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return "SCHED_MAIN"

    kb = []
    for g in groups:
        gid, platform, game_name, events_order, interval, gaid, af_uid, status, next_run = g
        status_emoji = "🟢" if status == "active" else "🔴"
        interval_text = "فوري" if interval == 0 else ("مخصص" if interval == -1 else (f"{interval}د" if interval < 60 else f"{interval // 60}س"))
        kb.append([InlineKeyboardButton(
            f"{status_emoji} [{gid}] {game_name} ({platform.upper()}) {interval_text}",
            callback_data=f"sched_group_info_{gid}"
        )])

    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="sched_menu")])
    await query.edit_message_text("📋 *مجموعاتي:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return "SCHED_GROUPS"

async def sched_group_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.replace("sched_group_info_", ""))
    uid = query.from_user.id

    g = c_main.execute(
        "SELECT id, platform, game_name, events_order, interval_minutes, gaid, af_uid, status, next_run FROM sched_groups WHERE id = ? AND user_id = ?",
        (gid, uid)
    ).fetchone()

    if not g:
        await query.edit_message_text("❌ المجموعة غير موجودة", parse_mode="Markdown")
        return "SCHED_GROUPS"

    gid, platform, game_name, events_order_raw, interval, gaid, af_uid, status, next_run = g
    try:
        events = json.loads(events_order_raw)
        if events and isinstance(events[0], dict) and "level" in events[0]:
            def _fmt(m):
                if m == 0: return "فوري"
                return f"{int(m)}د" if m < 60 else f"{m/60:.1f}س"
            events_text = "\n".join([f"{i+1}. LV{e['level']} ← بعد {_fmt(e['interval'])}" for i, e in enumerate(events)])
        else:
            events_text = "\n".join([f"{i+1}. {e[1]}" for i, e in enumerate(events)])
    except Exception:
        events_text = events_order_raw

    interval_text = "فوري (بدون فاصل)" if interval == 0 else ("مخصص لكل لفل" if interval == -1 else (f"{interval} دقيقة" if interval < 60 else f"{interval // 60} ساعة"))
    status_text = "🟢 نشطة" if status == "active" else "🔴 متوقفة"
    next_run_short = next_run[:16] if next_run else "-"

    kb = [
        [InlineKeyboardButton("⏹ إيقاف", callback_data=f"sched_stop_{gid}"),
         InlineKeyboardButton("▶️ تفعيل", callback_data=f"sched_activate_{gid}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"sched_delete_{gid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sched_my_groups")],
    ]
    await query.edit_message_text(
        f"📋 *تفاصيل المجموعة [{gid}]:*\n\n"
        f"🔹 *المنصة:* `{platform.upper()}`\n"
        f"🎮 *اللعبة:* `{game_name}`\n"
        f"🎯 *الأحداث:*\n{events_text}\n"
        f"⏰ *الفاصل:* `{interval_text}`\n"
        f"📱 *GAID:* `{gaid}`\n"
        f"🔑 *AF UID:* `{af_uid}`\n"
        f"📊 *الحالة:* {status_text}\n"
        f"⏭ *التنفيذ التالي:* `{next_run_short}`",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return "SCHED_GROUP_INFO"

async def sched_stop_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.replace("sched_stop_", ""))
    uid = query.from_user.id
    c_main.execute("UPDATE sched_groups SET status = 'stopped' WHERE id = ? AND user_id = ?", (gid, uid))
    conn_main.commit()
    stop_sched_task(gid)
    await query.answer("✅ تم الإيقاف", show_alert=True)
    return await sched_group_info(update, context)

async def sched_activate_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.replace("sched_activate_", ""))
    uid = query.from_user.id
    now = datetime.now().isoformat()
    c_main.execute("UPDATE sched_groups SET status = 'active', next_run = ? WHERE id = ? AND user_id = ?", (now, gid, uid))
    conn_main.commit()
    start_sched_task(context.bot, gid, uid)
    await query.answer("✅ تم التفعيل", show_alert=True)
    return await sched_group_info(update, context)

async def sched_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gid = int(query.data.replace("sched_delete_", ""))
    uid = query.from_user.id
    stop_sched_task(gid)
    c_main.execute("DELETE FROM sched_groups WHERE id = ? AND user_id = ?", (gid, uid))
    conn_main.commit()
    await query.edit_message_text("✅ *تم حذف المجموعة*", parse_mode="Markdown")
    return -1

async def sched_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await sched_menu(update, context)

async def sched_runner(context: ContextTypes.DEFAULT_TYPE):
    """يعمل عند بدء البوت لإعادة تشغيل المجموعات النشطة التي لها next_run منتهي"""
    try:
        now = datetime.now()
        groups = c_main.execute(
            "SELECT id, user_id FROM sched_groups WHERE status = 'active'",
        ).fetchall()
        for gid, uid in groups:
            start_sched_task(context.bot, gid, uid)
    except Exception as e:
        logger.error(f"sched_runner startup error: {e}")



def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # إضافة جدولة المزرعة
    try:
        job_queue = app.job_queue
        if job_queue:
            job_queue.run_repeating(farm_scheduler, interval=3600, first=10)
            job_queue.run_once(sched_runner, when=3)
            print("✅ جدولة المزرعة مفعلة")
        else:
            print("⚠️ JobQueue غير متاح - ميزة المزرعة العادية لن تعمل (الوضع الخاص يعمل بدونها)")
    except Exception as e:
        print(f"⚠️ خطأ في إعداد JobQueue: {e}")

    # Proxy Conversation (المطور)
    proxy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(proxy_settings, pattern="^proxy_settings$")],
        states={
            "PROXY_MAIN": [CallbackQueryHandler(proxy_add, pattern="^proxy_add$"), CallbackQueryHandler(proxy_del, pattern="^proxy_del$"), CallbackQueryHandler(proxy_test, pattern="^proxy_test$"), CallbackQueryHandler(main_menu, pattern="^main$")],
            "PROXY_TYPE": [CallbackQueryHandler(proxy_type_http, pattern="^proxy_type_http$"), CallbackQueryHandler(proxy_type_socks5, pattern="^proxy_type_socks5$"), CallbackQueryHandler(proxy_settings, pattern="^proxy_settings$")],
            "PROXY_IP_PORT": [MessageHandler(filters.TEXT & ~filters.COMMAND, proxy_ip_port)],
            "PROXY_AUTH": [CallbackQueryHandler(proxy_no_auth, pattern="^proxy_no_auth$"), CallbackQueryHandler(proxy_need_auth, pattern="^proxy_need_auth$"), CallbackQueryHandler(proxy_add, pattern="^proxy_add$")],
            "PROXY_USERNAME": [MessageHandler(filters.TEXT & ~filters.COMMAND, proxy_username)],
            "PROXY_PASSWORD": [MessageHandler(filters.TEXT & ~filters.COMMAND, proxy_password)],
        },
        fallbacks=[], allow_reentry=True
    )

    # AppsFlyer Conversation
    af_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(af_menu, pattern="^af$")],
        states={
            "AF_MAIN": [CallbackQueryHandler(af_show_games, pattern="^af_show_games$"), CallbackQueryHandler(af_search_game, pattern="^af_search_game$"), CallbackQueryHandler(main_menu, pattern="^main$")],
            "AF_SEARCH": [MessageHandler(filters.TEXT & ~filters.COMMAND, af_search)],
            "AF_GAME": [CallbackQueryHandler(af_game, pattern="^afgame_\\d+$"), CallbackQueryHandler(af_menu, pattern="^af_menu$")],
            "AF_IDFA": [MessageHandler(filters.TEXT & ~filters.COMMAND, af_idfa)],
            "AF_IDFV": [MessageHandler(filters.TEXT & ~filters.COMMAND, af_idfv)],
            "AF_UID": [MessageHandler(filters.TEXT & ~filters.COMMAND, af_uid_ios), MessageHandler(filters.TEXT & ~filters.COMMAND, af_uid)],
            "AF_GAID": [MessageHandler(filters.TEXT & ~filters.COMMAND, af_gaid)],
            "AF_TYPE": [CallbackQueryHandler(af_level, pattern="^af_level$"), CallbackQueryHandler(af_purchase, pattern="^af_purchase$"), CallbackQueryHandler(af_back, pattern="^af_back$")],
            "AF_SEND": [CallbackQueryHandler(af_send, pattern="^af_send_|^af_pay_"), CallbackQueryHandler(af_back, pattern="^af_back$"), CallbackQueryHandler(af_custom, pattern="^af_custom$")],
            "AF_CUSTOM": [MessageHandler(filters.TEXT & ~filters.COMMAND, af_custom_value), CallbackQueryHandler(af_level, pattern="^af_level$")],
            "AF_CUSTOM_CONFIRM": [CallbackQueryHandler(af_custom_confirm, pattern="^af_custom_confirm$"), CallbackQueryHandler(af_level, pattern="^af_level$")],
        },
        fallbacks=[], allow_reentry=True
    )

    # Adjust Conversation
    adj_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adj_menu, pattern="^adj$")],
        states={
            "ADJ_MAIN": [CallbackQueryHandler(adj_show_games, pattern="^adj_show_games$"), CallbackQueryHandler(adj_search_game, pattern="^adj_search_game$"), CallbackQueryHandler(main_menu, pattern="^main$")],
            "ADJ_SEARCH": [MessageHandler(filters.TEXT & ~filters.COMMAND, adj_search)],
            "ADJ_GAME": [CallbackQueryHandler(adj_game, pattern="^adjgame_\\d+$"), CallbackQueryHandler(adj_menu, pattern="^adj_menu$")],
            "ADJ_ADID": [MessageHandler(filters.TEXT & ~filters.COMMAND, adj_adid)],
            "ADJ_CUSTOM": [MessageHandler(filters.TEXT & ~filters.COMMAND, adj_custom_value)],
        },
        fallbacks=[], allow_reentry=True
    )

    # محادثة مستقلة لـ "لفل مخصص" في Adjust (إرسال فوري)
    adj_level_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adj_custom, pattern="^adj_custom$")],
        states={
            "ADJ_CUSTOM_LEVEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, adj_custom_level_input)],
        },
        fallbacks=[CallbackQueryHandler(adj_menu, pattern="^adj_menu$")],
        allow_reentry=True
    )

    # Singular Conversation
    singular_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(singular_menu, pattern="^singular$")],
        states={
            "SINGULAR_MAIN": [CallbackQueryHandler(singular_show_games, pattern="^singular_show_games$"), CallbackQueryHandler(singular_search_game, pattern="^singular_search_game$"), CallbackQueryHandler(main_menu, pattern="^main$")],
            "SINGULAR_SEARCH": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_search)],
            "SINGULAR_GAME": [CallbackQueryHandler(singular_game, pattern="^sgame_\\d+$"), CallbackQueryHandler(singular_menu, pattern="^singular_menu$")],
            "SINGULAR_IDFA": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_idfa)],
            "SINGULAR_IDFV": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_idfv)],
            "SINGULAR_UID": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_uid_ios), MessageHandler(filters.TEXT & ~filters.COMMAND, singular_uid)],
            "SINGULAR_AIFA": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_aifa)],
            "SINGULAR_CUSTOM": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_custom_value)],
        },
        fallbacks=[], allow_reentry=True
    )

    # محادثة مستقلة لـ "لفل مخصص" في Singular (إرسال فوري)
    singular_level_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(singular_custom_level, pattern="^singular_custom_level$")],
        states={
            "SINGULAR_CUSTOM_LEVEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, singular_custom_level_value)],
        },
        fallbacks=[CallbackQueryHandler(singular_menu, pattern="^singular_menu$")],
        allow_reentry=True
    )

    # Sched Conversation (جدولة العمليات)
    sched_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(sched_menu, pattern="^sched_menu$")],
        states={
            "SCHED_MAIN": [
                CallbackQueryHandler(sched_new, pattern="^sched_new$"),
                CallbackQueryHandler(sched_my_groups, pattern="^sched_my_groups$"),
                CallbackQueryHandler(main_menu, pattern="^main$"),
            ],
            "SCHED_PLATFORM": [
                CallbackQueryHandler(sched_platform_select, pattern="^sched_platform_"),
                CallbackQueryHandler(sched_back_to_menu, pattern="^sched_menu$"),
            ],
            "SCHED_GAME": [
                CallbackQueryHandler(sched_game_select, pattern=r"^sched_game_\d+$"),
                CallbackQueryHandler(sched_new, pattern="^sched_new$"),
            ],
            "SCHED_LEVELS": [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sched_levels_input),
            ],
            "SCHED_EVENTS": [
                CallbackQueryHandler(sched_event_toggle, pattern=r"^sched_ev_\d+$"),
                CallbackQueryHandler(sched_save_events, pattern="^sched_save_events$"),
                CallbackQueryHandler(sched_new, pattern="^sched_new$"),
            ],
            "SCHED_INTERVAL": [
                CallbackQueryHandler(sched_interval_select, pattern="^sched_interval_"),
                CallbackQueryHandler(sched_save_events, pattern="^sched_back_events$"),
            ],
            "SCHED_GAID": [MessageHandler(filters.TEXT & ~filters.COMMAND, sched_gaid_input)],
            "SCHED_AFUID": [MessageHandler(filters.TEXT & ~filters.COMMAND, sched_afuid_input)],
            "SCHED_CONFIRM": [
                CallbackQueryHandler(sched_confirm, pattern="^sched_confirm$"),
                CallbackQueryHandler(sched_back_to_menu, pattern="^sched_menu$"),
            ],
            "SCHED_GROUPS": [
                CallbackQueryHandler(sched_group_info, pattern=r"^sched_group_info_\d+$"),
                CallbackQueryHandler(sched_back_to_menu, pattern="^sched_menu$"),
            ],
            "SCHED_GROUP_INFO": [
                CallbackQueryHandler(sched_stop_group, pattern=r"^sched_stop_\d+$"),
                CallbackQueryHandler(sched_activate_group, pattern=r"^sched_activate_\d+$"),
                CallbackQueryHandler(sched_delete_group, pattern=r"^sched_delete_\d+$"),
                CallbackQueryHandler(sched_my_groups, pattern="^sched_my_groups$"),
            ],
        },
        fallbacks=[], allow_reentry=True
    )

    # Farm Conversation (المطورة)
    farm_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(jumper_farm_menu, pattern="^jumper_farm$")],
        states={
            "FARM_MAIN": [CallbackQueryHandler(farm_new, pattern="^farm_new$"), CallbackQueryHandler(farm_list, pattern="^farm_list$"), CallbackQueryHandler(farm_special, pattern="^farm_special$"), CallbackQueryHandler(farm_stop, pattern="^farm_stop$"), CallbackQueryHandler(main_menu, pattern="^main$")],
            "FARM_PLATFORM": [CallbackQueryHandler(farm_platform_af, pattern="^farm_platform_af$"), CallbackQueryHandler(farm_platform_adj, pattern="^farm_platform_adj$"), CallbackQueryHandler(farm_platform_singular, pattern="^farm_platform_singular$"), CallbackQueryHandler(jumper_farm_menu, pattern="^jumper_farm$")],
            "FARM_GAME": [CallbackQueryHandler(farm_game_select, pattern="^farm_game_"), CallbackQueryHandler(jumper_farm_menu, pattern="^jumper_farm$")],
            "FARM_GAID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_gaid)],
            "FARM_AF_UID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_af_uid), MessageHandler(filters.TEXT & ~filters.COMMAND, farm_af_uid_ios)],
            "FARM_GPS_ADID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_gps_adid)],
            "FARM_AIFA": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_aifa)],
            "FARM_SINGULAR_UID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_singular_uid), MessageHandler(filters.TEXT & ~filters.COMMAND, farm_singular_uid_ios)],
            "FARM_IDFA_AF": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_idfa_af)],
            "FARM_IDFV_AF": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_idfv_af)],
            "FARM_IDFA_SINGULAR": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_idfa_singular)],
            "FARM_IDFV_SINGULAR": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_idfv_singular)],
            "FARM_START_LEVEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_start_level)],
            "FARM_END_LEVEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_end_level)],
            "FARM_TOTAL_DAYS": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_total_days)],
            "FARM_MODE": [CallbackQueryHandler(farm_mode_select, pattern="^farm_mode_")],
            "FARM_CONFIRM": [CallbackQueryHandler(farm_confirm, pattern="^farm_confirm$")],
            "FARM_STOP_SELECT": [CallbackQueryHandler(farm_stop_task, pattern="^farm_stop_task_"), CallbackQueryHandler(jumper_farm_menu, pattern="^jumper_farm$")],
            "FARM_EDIT_SELECT": [CallbackQueryHandler(farm_edit_task, pattern="^farm_edit_")],
            "FARM_EDIT_ACTION": [CallbackQueryHandler(farm_hit_now, pattern="^farm_hit_now_"), CallbackQueryHandler(farm_delete_level, pattern="^farm_delete_level_"), CallbackQueryHandler(farm_change_level, pattern="^farm_change_level_"), CallbackQueryHandler(farm_edit_list, pattern="^farm_edit_list$")],
            "FARM_DELETE_LEVEL_INPUT": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_delete_level_input)],
            "FARM_CHANGE_LEVEL_INPUT": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_change_level_input)],
            "FARM_SPECIAL_PLATFORM": [CallbackQueryHandler(farm_special_platform_af, pattern="^farm_special_af$"), CallbackQueryHandler(farm_special_platform_adj, pattern="^farm_special_adj$"), CallbackQueryHandler(farm_special_platform_singular, pattern="^farm_special_singular$"), CallbackQueryHandler(jumper_farm_menu, pattern="^jumper_farm$")],
            "FARM_SPECIAL_GAME": [CallbackQueryHandler(farm_special_game_select, pattern="^farm_special_game_"), CallbackQueryHandler(farm_special, pattern="^farm_special$")],
            "FARM_SPECIAL_IDFA_AF": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_idfa_af)],
            "FARM_SPECIAL_IDFV_AF": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_idfv_af)],
            "FARM_SPECIAL_AF_UID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_af_uid), MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_af_uid_ios)],
            "FARM_SPECIAL_GAID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_gaid)],
            "FARM_SPECIAL_GPS_ADID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_gps_adid)],
            "FARM_SPECIAL_IDFA_SINGULAR": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_idfa_singular)],
            "FARM_SPECIAL_IDFV_SINGULAR": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_idfv_singular)],
            "FARM_SPECIAL_SINGULAR_UID": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_singular_uid), MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_singular_uid_ios)],
            "FARM_SPECIAL_AIFA": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_aifa)],
            "FARM_SPECIAL_START_LEVEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_start_level)],
            "FARM_SPECIAL_END_LEVEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_end_level)],
            "FARM_SPECIAL_TIME": [CallbackQueryHandler(farm_special_time_select, pattern="^special_time_")],
            "FARM_SPECIAL_TIME_VALUE": [MessageHandler(filters.TEXT & ~filters.COMMAND, farm_special_time_value)],
        },
        fallbacks=[], allow_reentry=True
    )

    # Admin Conversations
    admin_add_user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_user, pattern="^admin_add_user$")],
        states={"ADMIN_ADD_USER": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_process)]},
        fallbacks=[], allow_reentry=True
    )
    admin_remove_user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_remove_user, pattern="^admin_remove_user$")],
        states={"ADMIN_REMOVE_USER": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_user_process)]},
        fallbacks=[], allow_reentry=True
    )
    admin_ban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_ban, pattern="^admin_ban$")],
        states={"ADMIN_BAN": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_ban_user)]},
        fallbacks=[], allow_reentry=True
    )
    admin_unban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_unban, pattern="^admin_unban$")],
        states={"ADMIN_UNBAN": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_unban_user)]},
        fallbacks=[], allow_reentry=True
    )
    admin_broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$")],
        states={
            "ADMIN_BROADCAST_MSG": [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_get_broadcast_msg)],
            "ADMIN_BROADCAST_CONFIRM": [CallbackQueryHandler(admin_broadcast_confirm, pattern="^broadcast_")],
        },
        fallbacks=[], allow_reentry=True
    )
    admin_add_game_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_game, pattern="^admin_add_game$")],
        states={
            "ADD_GAME_TYPE": [CallbackQueryHandler(add_game_af, pattern="^add_game_af$"), CallbackQueryHandler(add_game_adj, pattern="^add_game_adj$"), CallbackQueryHandler(add_game_singular, pattern="^add_game_singular$"), CallbackQueryHandler(admin_panel, pattern="^admin$")],
            "ADD_GAME_NAME": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_game_name)],
            "ADD_GAME_DISPLAY": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_game_display)],
            "ADD_GAME_PACKAGE": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_game_package)],
            "ADD_GAME_KEY": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_game_key)],
            "ADD_GAME_EMOJI": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_game_emoji)],
        },
        fallbacks=[], allow_reentry=True
    )
    admin_delete_game_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_delete_game, pattern="^admin_delete_game$")],
        states={
            "DEL_GAME_TYPE": [CallbackQueryHandler(del_game_af, pattern="^del_game_af$"), CallbackQueryHandler(del_game_adj, pattern="^del_game_adj$"), CallbackQueryHandler(del_game_singular, pattern="^del_game_singular$"), CallbackQueryHandler(admin_panel, pattern="^admin$")],
            "DEL_GAME_SELECT": [CallbackQueryHandler(del_game_confirm, pattern="^del_af_\\d+$"), CallbackQueryHandler(del_game_confirm, pattern="^del_adj_\\d+$"), CallbackQueryHandler(del_game_confirm, pattern="^del_singular_\\d+$"), CallbackQueryHandler(admin_delete_game, pattern="^admin_delete_game$")],
        },
        fallbacks=[], allow_reentry=True
    )
    admin_add_event_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_event, pattern="^admin_add_event$")],
        states={
            "ADD_EVENT_TYPE": [CallbackQueryHandler(add_event_af, pattern="^add_event_af$"), CallbackQueryHandler(add_event_adj, pattern="^add_event_adj$"), CallbackQueryHandler(add_event_singular, pattern="^add_event_singular$"), CallbackQueryHandler(admin_panel, pattern="^admin$")],
            "ADD_EVENT_GAME": [CallbackQueryHandler(add_event_game, pattern="^ev_af_\\d+$"), CallbackQueryHandler(add_event_game, pattern="^ev_adj_\\d+$"), CallbackQueryHandler(add_event_game, pattern="^ev_singular_\\d+$"), CallbackQueryHandler(admin_add_event, pattern="^admin_add_event$")],
            "ADD_EVENT_NAME": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_name)],
            "ADD_EVENT_TOKEN": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_token)],
            "ADD_EVENT_DISPLAY": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_display)],
            "ADD_EVENT_DISPLAY_ADJ": [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_display_adj)],
        },
        fallbacks=[], allow_reentry=True
    )
    admin_delete_event_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_delete_event, pattern="^admin_delete_event$")],
        states={
            "DEL_EVENT_TYPE": [CallbackQueryHandler(del_event_af, pattern="^del_event_af$"), CallbackQueryHandler(del_event_adj, pattern="^del_event_adj$"), CallbackQueryHandler(del_event_singular, pattern="^del_event_singular$"), CallbackQueryHandler(admin_panel, pattern="^admin$")],
            "DEL_EVENT_GAME": [CallbackQueryHandler(del_event_game, pattern="^dev_af_\\d+$"), CallbackQueryHandler(del_event_game, pattern="^dev_adj_\\d+$"), CallbackQueryHandler(del_event_game, pattern="^dev_singular_\\d+$"), CallbackQueryHandler(admin_delete_event, pattern="^admin_delete_event$")],
            "DEL_EVENT_SELECT": [CallbackQueryHandler(del_event_confirm, pattern="^delev_af_\\d+$"), CallbackQueryHandler(del_event_confirm, pattern="^delev_adj_\\d+$"), CallbackQueryHandler(del_event_confirm, pattern="^delev_singular_\\d+$"), CallbackQueryHandler(admin_delete_event, pattern="^admin_delete_event$")],
        },
        fallbacks=[], allow_reentry=True
    )

    # إضافة جميع المعالجات
    # محادثات "لفل مخصص" أولاً بأولوية أعلى من المحادثات الرئيسية
    # حتى تلتقط رسائل رقم اللفل قبل أي conversation handler آخر
    app.add_handler(adj_level_conv)
    app.add_handler(singular_level_conv)
    app.add_handler(proxy_conv)
    app.add_handler(af_conv)
    app.add_handler(adj_conv)
    app.add_handler(singular_conv)
    app.add_handler(farm_conv)
    app.add_handler(sched_conv)
    app.add_handler(admin_add_user_conv)
    app.add_handler(admin_remove_user_conv)
    app.add_handler(admin_ban_conv)
    app.add_handler(admin_unban_conv)
    app.add_handler(admin_broadcast_conv)
    app.add_handler(admin_add_game_conv)
    app.add_handler(admin_delete_game_conv)
    app.add_handler(admin_add_event_conv)
    app.add_handler(admin_delete_event_conv)
    
    # معالجات إضافية
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_allowed_list, pattern="^admin_allowed_list$"))
    app.add_handler(CallbackQueryHandler(admin_banned_list, pattern="^admin_banned_list$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(select_platform, pattern="^select_platform$"))
    app.add_handler(CallbackQueryHandler(set_platform_android, pattern="^set_platform_android$"))
    app.add_handler(CallbackQueryHandler(set_platform_ios, pattern="^set_platform_ios$"))
    app.add_handler(CallbackQueryHandler(adj_resend, pattern="^adj_resend_\\d+$"))
    app.add_handler(CallbackQueryHandler(adj_send, pattern="^adj_send_"))
    app.add_handler(CallbackQueryHandler(singular_send, pattern="^singular_send_"))
    app.add_handler(CallbackQueryHandler(singular_resend, pattern="^singular_resend_\\d+$"))
    app.add_handler(CallbackQueryHandler(singular_custom, pattern="^singular_custom$"))
    app.add_handler(CallbackQueryHandler(singular_custom_level_confirm, pattern="^sg_custom_level_confirm$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CommandHandler("start", start))

    print("=" * 60)
    print("✅ AK Bot شغال - النسخة النهائية الكاملة")
    print(f"👑 المديرين: {ADMIN_IDS}")
    print(f"📞 الدعم: {SUPPORT_USER}")
    print("=" * 60)
    app.run_polling()

if __name__ == "__main__":
    main()

    print("=" * 60)
    print("✅ AK Bot شغال - النسخة النهائية الكاملة")
    print(f"👑 المديرين: {ADMIN_IDS}")
    print(f"📞 الدعم: {SUPPORT_USER}")
    print("=" * 60)
    app.run_polling()

if __name__ == "__main__":
    main()
