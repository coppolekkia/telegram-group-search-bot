import os
import logging
import asyncio
import aiohttp
import json
import re
from datetime import datetime
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import TelegramError
import urllib.parse

# Configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token del bot
BOT_TOKEN = os.getenv('BOT_TOKEN')

class GroupSearchDB:
    def __init__(self, db_file='groups_search.db'):
        self.db_file = db_file
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS searched_groups (
                id INTEGER PRIMARY KEY,
                group_name TEXT,
                group_username TEXT,
                group_description TEXT,
                members_count INTEGER,
                group_type TEXT,
                invite_link TEXT,
                search_query TEXT,
                found_date DATETIME,
                is_verified INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                search_query TEXT,
                results_count INTEGER,
                search_date DATETIME
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_group(self, group_name, group_username, group_description, members_count, 
                   group_type, invite_link, search_query):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO searched_groups 
            (group_name, group_username, group_description, members_count, 
             group_type, invite_link, search_query, found_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (group_name, group_username, group_description, members_count,
              group_type, invite_link, search_query, datetime.now()))
        conn.commit()
        conn.close()
    
    def save_search(self, user_id, search_query, results_count):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO search_history 
            (user_id, search_query, results_count, search_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, search_query, results_count, datetime.now()))
        conn.commit()
        conn.close()
    
    def get_saved_groups(self, search_query, limit=20):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT group_name, group_username, group_description, members_count, 
                   group_type, invite_link
            FROM searched_groups 
            WHERE search_query LIKE ? OR group_name LIKE ? OR group_description LIKE ?
            ORDER BY members_count DESC, found_date DESC
            LIMIT ?
        ''', (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", limit))
        
        results = cursor.fetchall()
        conn.close()
        return results

# Inizializza database
db = GroupSearchDB()

class TelegramGroupSearcher:
    def __init__(self):
        self.session = None
    
    async def create_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        if self.session:
            await self.session.close()
    
    async def search_groups_web(self, query, limit=15):
        """Cerca gruppi usando varie fonti web"""
        results = []
        
        # Cerca su diverse piattaforme
        sources = [
            await self.search_telegram_me(query, limit//3),
            await self.search_tlgrm_eu(query, limit//3),
            await self.search_tgstat(query, limit//3)
        ]
        
        for source_results in sources:
            results.extend(source_results)
        
        # Rimuovi duplicati
        seen = set()
        unique_results = []
        for result in results:
            identifier = result.get('username', '') + result.get('title', '')
            if identifier not in seen:
                seen.add(identifier)
                unique_results.append(result)
        
        return unique_results[:limit]
    
    async def search_telegram_me(self, query, limit=5):
        """Cerca su telegram.me"""
        await self.create_session()
        results = []
        
        try:
            search_url = f"https://telegram.me/s/{urllib.parse.quote(query)}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with self.session.get(search_url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    # Parsing semplificato - nella realtà useresti BeautifulSoup
                    # Qui simuliamo alcuni risultati per l'esempio
                    results.append({
                        'title': f"Gruppo {query.title()}",
                        'username': f"{query.lower().replace(' ', '')}_group",
                        'description': f"Gruppo dedicato a {query}",
                        'members': "5.2K",
                        'link': f"https://t.me/{query.lower().replace(' ', '')}_group"
                    })
        
        except Exception as e:
            logger.error(f"Errore ricerca telegram.me: {e}")
        
        return results
    
    async def search_tlgrm_eu(self, query, limit=5):
        """Cerca su tlgrm.eu (directory gruppi)"""
        results = []
        
        # Simulazione ricerca - sostituire con API reale
        mock_groups = [
            {
                'title': f"{query.title()} Community",
                'username': f"{query.lower()}_community",
                'description': f"Community italiana di {query}",
                'members': "12.5K",
                'link': f"https://t.me/{query.lower()}_community"
            },
            {
                'title': f"{query.title()} News",
                'username': f"{query.lower()}_news",
                'description': f"Notizie e aggiornamenti su {query}",
                'members': "8.7K",
                'link': f"https://t.me/{query.lower()}_news"
            }
        ]
        
        return mock_groups[:limit]
    
    async def search_tgstat(self, query, limit=5):
        """Cerca su TGStat"""
        results = []
        
        # Simulazione - sostituire con API TGStat se disponibile
        mock_results = [
            {
                'title': f"{query.title()} Official",
                'username': f"official_{query.lower()}",
                'description': f"Canale ufficiale {query}",
                'members': "25.1K",
                'link': f"https://t.me/official_{query.lower()}"
            }
        ]
        
        return mock_results[:limit]
    
    async def get_group_info(self, username_or_link):
        """Ottieni informazioni dettagliate di un gruppo"""
        await self.create_session()
        
        try:
            # Estrai username dal link
            if 't.me/' in username_or_link:
                username = username_or_link.split('t.me/')[-1]
            else:
                username = username_or_link.replace('@', '')
            
            # Qui useresti l'API di Telegram per ottenere info reali
            # Per ora simuliamo
            return {
                'title': f"Gruppo {username}",
                'username': username,
                'description': "Descrizione del gruppo",
                'members_count': 1500,
                'is_verified': False,
                'invite_link': f"https://t.me/{username}"
            }
            
        except Exception as e:
            logger.error(f"Errore nel recuperare info gruppo: {e}")
            return None

# Inizializza searcher
searcher = TelegramGroupSearcher()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per il comando /start"""
    welcome_text = """
🔍 **Bot Ricerca Gruppi Telegram**

Trova facilmente gruppi Telegram per i tuoi interessi!

**🎯 Comandi principali:**
• `/cerca <argomento>` - Cerca gruppi per argomento
• `/info <@username>` - Info dettagliate di un gruppo
• `/trending` - Gruppi di tendenza
• `/categorie` - Cerca per categorie
• `/help` - Guida completa

**📌 Esempi:**
• `/cerca crypto` - Gruppi di criptovalute
• `/cerca milano` - Gruppi di Milano  
• `/cerca gaming` - Gruppi di gaming

Inizia subito con una ricerca! 🚀
    """
    
    keyboard = [
        [InlineKeyboardButton("🔍 Cerca Gruppi", callback_data="search_prompt")],
        [InlineKeyboardButton("📊 Categorie", callback_data="categories"), 
         InlineKeyboardButton("🔥 Trending", callback_data="trending")],
        [InlineKeyboardButton("❓ Aiuto", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per il comando /cerca"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Specifica cosa cercare!**\n\n"
            "Esempio: `/cerca crypto`\n"
            "Esempio: `/cerca milano calcio`", 
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    query = " ".join(context.args)
    user_id = update.effective_user.id
    
    # Messaggio di caricamento
    loading_msg = await update.message.reply_text("🔍 Ricerca in corso... ⏳")
    
    try:
        # Cerca gruppi
        results = await searcher.search_groups_web(query)
        
        if not results:
            await loading_msg.edit_text(
                f"❌ **Nessun gruppo trovato per:** `{query}`\n\n"
                "💡 **Suggerimenti:**\n"
                "• Prova parole diverse\n"
                "• Usa termini più generici\n" 
                "• Controlla l'ortografia",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Salva risultati nel database
        for result in results:
            db.save_group(
                result.get('title', ''),
                result.get('username', ''),
                result.get('description', ''),
                result.get('members', '0'),
                'group',
                result.get('link', ''),
                query
            )
        
        # Salva ricerca
        db.save_search(user_id, query, len(results))
        
        # Prepara risposta
        response = f"🎯 **Risultati per:** `{query}`\n"
        response += f"📊 **Trovati:** {len(results)} gruppi\n\n"
        
        for i, group in enumerate(results[:8], 1):
            title = group.get('title', 'Senza titolo')
            username = group.get('username', '')
            description = group.get('description', 'Nessuna descrizione')[:80]
            members = group.get('members', 'N/A')
            link = group.get('link', '')
            
            response += f"**{i}. {title}**\n"
            if username:
                response += f"🆔 @{username}\n"
            response += f"👥 {members} membri\n"
            response += f"📝 {description}...\n"
            if link:
                response += f"🔗 [Unisciti]({link})\n"
            response += "\n"
        
        if len(results) > 8:
            response += f"➕ **E altri {len(results) - 8} gruppi...**\n"
            response += "Usa `/info @username` per dettagli specifici"
        
        # Bottoni azione
        keyboard = [
            [InlineKeyboardButton("🔄 Nuova Ricerca", callback_data="search_prompt")],
            [InlineKeyboardButton("💾 Salva Preferiti", callback_data=f"save_search_{query}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await loading_msg.edit_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        
    except Exception as e:
        logger.error(f"Errore nella ricerca: {e}")
        await loading_msg.edit_text("❌ Errore durante la ricerca. Riprova tra poco.")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per il comando /info"""
    if not context.args:
        await update.message.reply_text(
            "❌ **Specifica un gruppo!**\n\n"
            "Esempio: `/info @cryptoitalia`\n"
            "Esempio: `/info https://t.me/cryptoitalia`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    group_identifier = context.args[0]
    loading_msg = await update.message.reply_text("ℹ️ Recupero informazioni... ⏳")
    
    try:
        group_info = await searcher.get_group_info(group_identifier)
        
        if not group_info:
            await loading_msg.edit_text(f"❌ Impossibile trovare informazioni per: `{group_identifier}`", parse_mode=ParseMode.MARKDOWN)
            return
        
        response = f"📋 **Informazioni Gruppo**\n\n"
        response += f"**📛 Nome:** {group_info.get('title', 'N/A')}\n"
        response += f"**🆔 Username:** @{group_info.get('username', 'N/A')}\n"
        response += f"**👥 Membri:** {group_info.get('members_count', 'N/A'):,}\n"
        response += f"**✅ Verificato:** {'Sì' if group_info.get('is_verified') else 'No'}\n\n"
        
        if group_info.get('description'):
            response += f"**📝 Descrizione:**\n{group_info['description'][:200]}...\n\n"
        
        if group_info.get('invite_link'):
            response += f"🔗 **[Unisciti al Gruppo]({group_info['invite_link']})**"
        
        keyboard = [
            [InlineKeyboardButton("🔍 Cerca Altri", callback_data="search_prompt")],
            [InlineKeyboardButton("💾 Salva", callback_data=f"save_group_{group_info.get('username', '')}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await loading_msg.edit_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        
    except Exception as e:
        logger.error(f"Errore recupero info: {e}")
        await loading_msg.edit_text("❌ Errore nel recuperare le informazioni.")

async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per gruppi di tendenza"""
    trending_groups = [
        {"title": "Crypto Italia", "username": "cryptoitalia", "members": "45.2K", "category": "💰 Crypto"},
        {"title": "Tech News Italia", "username": "technewsit", "members": "38.7K", "category": "💻 Tech"},
        {"title": "Gaming Community", "username": "gaming_ita", "members": "29.1K", "category": "🎮 Gaming"},
        {"title": "Milano Eventi", "username": "milanoeventi", "members": "22.5K", "category": "🏙️ Città"},
        {"title": "Startup Italia", "username": "startupitalia", "members": "18.9K", "category": "🚀 Business"},
    ]
    
    response = "🔥 **Gruppi di Tendenza**\n\n"
    
    for i, group in enumerate(trending_groups, 1):
        response += f"**{i}. {group['title']}**\n"
        response += f"{group['category']} • 👥 {group['members']}\n"
        response += f"🔗 https://t.me/{group['username']}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔍 Cerca Specifico", callback_data="search_prompt")],
        [InlineKeyboardButton("📊 Categorie", callback_data="categories")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(response, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per le categorie"""
    categories_text = """
📊 **Categorie Popolari**

Scegli una categoria per trovare i migliori gruppi:
    """
    
    keyboard = [
        [InlineKeyboardButton("💰 Crypto", callback_data="cat_crypto"), 
         InlineKeyboardButton("💻 Tech", callback_data="cat_tech")],
        [InlineKeyboardButton("🎮 Gaming", callback_data="cat_gaming"), 
         InlineKeyboardButton("📚 Studio", callback_data="cat_studio")],
        [InlineKeyboardButton("🏙️ Città", callback_data="cat_citta"), 
         InlineKeyboardButton("🍕 Food", callback_data="cat_food")],
        [InlineKeyboardButton("⚽ Sport", callback_data="cat_sport"), 
         InlineKeyboardButton("🎵 Musica", callback_data="cat_musica")],
        [InlineKeyboardButton("🎬 Cinema", callback_data="cat_cinema"), 
         InlineKeyboardButton("🚗 Auto", callback_data="cat_auto")],
        [InlineKeyboardButton("🔍 Ricerca Libera", callback_data="search_prompt")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(categories_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per i callback dei bottoni"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "search_prompt":
        await query.edit_message_text(
            "🔍 **Inizia una ricerca**\n\n"
            "Scrivi: `/cerca <quello che cerchi>`\n\n"
            "**Esempi:**\n"
            "• `/cerca crypto bitcoin`\n"
            "• `/cerca roma calcio`\n"
            "• `/cerca programmazione python`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif query.data == "categories":
        await categories_command(update, context)
    
    elif query.data == "trending":
        await trending_command(update, context)
    
    elif query.data.startswith("cat_"):
        category = query.data.replace("cat_", "")
        # Simula ricerca per categoria
        await query.edit_message_text(f"🔍 Ricerca per categoria: {category}")
        # Qui implementeresti la ricerca specifica per categoria
    
    elif query.data == "help":
        help_text = """
❓ **Guida Completa**

**🔍 Comandi di Ricerca:**
• `/cerca <argomento>` - Cerca gruppi
• `/info <@username>` - Info dettagliate
• `/trending` - Gruppi popolari
• `/categorie` - Naviga per categorie

**💡 Consigli per Ricerche Efficaci:**
• Usa parole chiave specifiche
• Prova diverse combinazioni
• Usa termini in italiano e inglese

**🎯 Esempi di Ricerca:**
• Interessi: `crypto`, `gaming`, `tech`
• Luoghi: `milano`, `roma`, `napoli`
• Hobby: `fotografia`, `cucina`, `sport`

**⚡ Funzioni Avanzate:**
• Salvataggio ricerche preferite
• Filtraggio per numero membri
• Controllo gruppi verificati
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Indietro", callback_data="start_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per il comando /help"""
    await button_callback(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handler per gli errori"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Funzione principale"""
    if not BOT_TOKEN:
        print("❌ ERRORE: BOT_TOKEN non trovato nelle variabili d'ambiente!")
        return
    
    # Crea l'applicazione
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Aggiungi gli handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cerca", search_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("trending", trending_command))
    application.add_handler(CommandHandler("categorie", categories_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Handler per gli errori
    application.add_error_handler(error_handler)
    
    # Avvia il bot
    print("🚀 Bot Ricerca Gruppi avviato!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
