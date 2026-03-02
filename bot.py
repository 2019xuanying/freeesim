import logging
import asyncio
import sqlite3
import os
import time
from functools import wraps
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest

# ================= 配置区 =================
# 建议在实际部署时使用环境变量，这里为了方便你测试，可以直接在这里修改
BOT_TOKEN = os.getenv("BOT_TOKEN", "你的机器人的TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "你的Telegram用户ID")) # 纯数字ID
REQUIRED_CHAT_ID = os.getenv("REQUIRED_CHAT_ID", "@你的群组或频道用户名") # 例如 @my_channel_123

# ================= 初始化 =================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局发码锁，确保并发请求排队，避免一码多发
claim_lock = asyncio.Lock()

# ================= 数据库操作 =================
def init_db():
    conn = sqlite3.connect('esim_bot.db')
    cursor = conn.cursor()
    # 用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            verified INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            claimed_count INTEGER DEFAULT 0,
            freeze_time INTEGER DEFAULT 0
        )
    ''')
    # 尝试添加新字段以兼容旧数据库
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN freeze_time INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass # 字段已存在
    # eSIM库存表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS esims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            is_used INTEGER DEFAULT 0,
            claimed_by INTEGER,
            claim_time TIMESTAMP
        )
    ''')
    # 系统设置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    # 初始化机器人开关为开启状态
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("is_active", "1")')
    conn.commit()
    conn.close()

def db_execute(query, args=(), fetchone=False, fetchall=False):
    conn = sqlite3.connect('esim_bot.db')
    cursor = conn.cursor()
    cursor.execute(query, args)
    if fetchone:
        res = cursor.fetchone()
    elif fetchall:
        res = cursor.fetchall()
    else:
        res = None
        conn.commit()
    conn.close()
    return res

# ================= 装饰器 & 检查器 =================
async def check_membership(bot, user_id):
    """检查用户是否在指定群组中"""
    if not REQUIRED_CHAT_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHAT_ID, user_id=user_id)
        if member.status in ['left', 'kicked']:
            return False
        return True
    except BadRequest as e:
        logger.error(f"无法检查用户是否在群组中: {e}")
        # 如果机器人不在群组里，默认放行避免卡死，并记录错误
        return True 

def get_or_create_user(user_id):
    user = db_execute('SELECT verified, banned, claimed_count, freeze_time FROM users WHERE user_id = ?', (user_id,), fetchone=True)
    if not user:
        db_execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
        return (0, 0, 0, 0)
    return user

def admin_only(func):
    """管理员权限装饰器"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔️ 权限不足，仅管理员可执行此操作。")
            return
        return await func(update, context)
    return wrapper

# ================= 用户功能 =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    verified, banned, _, _ = get_or_create_user(user_id)
    
    if banned:
        await update.message.reply_text("⛔️ 你已被管理员拉黑，无法使用此机器人。")
        return
        
    if not verified:
        await update.message.reply_text(
            "👋 欢迎！在使用机器人领取免费 eSIM 之前，请先回答口令验证：\n\n"
            "❓ <b>提示：</b> 宫廷玉液酒的下一句？\n"
            "（请直接输入你的答案）", 
            parse_mode='HTML'
        )
        return
        
    await show_main_menu(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    verified, banned, _, _ = get_or_create_user(user_id)
    
    if banned:
        return # 被拉黑者发消息不回复

    if not verified:
        if text == "一百八一杯":
            db_execute('UPDATE users SET verified = 1 WHERE user_id = ?', (user_id,))
            await update.message.reply_text("✅ 口令正确！验证通过。")
            await show_main_menu(update, context)
        else:
            await update.message.reply_text("❌ 口令错误，请重新输入。\n提示：宫廷玉液酒的下一句？")
        return

    # 已验证用户的其他消息处理（暂无，可扩展）
    pass

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    menu_text = (
        "🤖 <b>eSIM 免费领取机器人</b>\n\n"
        "点击 /get_esim 尝试领取免费的 eSIM 套餐！\n\n"
        f"⚠️ 注意：你必须加入我们的频道/群组 {REQUIRED_CHAT_ID} 才能领取。"
    )
    
    # 检测是否为管理员，如果是，则追加管理面板说明
    if user_id == ADMIN_ID:
        menu_text += (
            "\n\n👑 <b>管理员控制面板</b> 👑\n"
            "作为管理员，您可以直接点击或输入以下命令：\n\n"
            "🔹 /stats - 查看当前库存统计\n"
            "🔹 /toggle - 开启/关闭机器人领取功能\n"
            "🔹 <code>/add_esim 激活码1 激活码2</code> - 批量添加库存 (注意空格)\n"
            "🔹 <code>/ban 用户ID</code> - 拉黑违规用户\n"
            "🔹 <code>/unban 用户ID</code> - 解封用户"
        )
        
    await update.message.reply_text(menu_text, parse_mode='HTML')

async def claim_esim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    verified, banned, claimed_count, freeze_time = get_or_create_user(user_id)

    if banned: return
    
    # 检查账户是否在冻结期
    current_time = int(time.time())
    if freeze_time > current_time:
        remaining_minutes = (freeze_time - current_time) // 60
        await update.message.reply_text(f"❄️ 你的账户正处于冻结状态，请等待 {remaining_minutes} 分钟后再试。")
        return

    if not verified:
        await update.message.reply_text("请先输入正确的口令进行验证。")
        return
        
    # 检查领取次数限制 (每人最多2次)
    if claimed_count >= 2:
        await update.message.reply_text("⛔️ 领取失败：每个用户最多只能领取 2 次 eSIM 套餐。")
        return
        
    # 检查是否设置了用户名，防小号
    if not update.effective_user.username:
        new_freeze_time = current_time + 2 * 3600 # 冻结2小时 (2 * 60 * 60 秒)
        db_execute('UPDATE users SET freeze_time = ? WHERE user_id = ?', (new_freeze_time, user_id))
        await update.message.reply_text("❌ 领取失败：你的 Telegram 账号未设置用户名 (@username)。\n\n为了防止机器小号，必须设置用户名。你的账号已被暂时冻结 2 小时，请设置用户名后等待解冻。")
        return

    # 检查是否在群
    is_member = await check_membership(context.bot, user_id)
    if not is_member:
        await update.message.reply_text(f"❌ 领取失败！\n你必须先加入 {REQUIRED_CHAT_ID} 才能领取。加入后请重试。")
        return

    # 检查全局开关
    is_active = db_execute('SELECT value FROM settings WHERE key = "is_active"', fetchone=True)[0]
    if is_active == "0":
        await update.message.reply_text("⏸️ 管理员暂时关闭了领取功能，请晚些时候再来。")
        return

    # 排队逻辑锁：同一时间只能有一个人执行下方的取码逻辑
    async with claim_lock:
        # 查询是否有未使用的代码
        esim = db_execute('SELECT id, code FROM esims WHERE is_used = 0 LIMIT 1', fetchone=True)
        
        if not esim:
            await update.message.reply_text("😭 抱歉，当前库存已经被领空了，请等待管理员补充库存！")
            return
            
        esim_id, esim_code = esim
        
        # 将代码标记为已使用 (直接更新，而不是删除，方便日后查账，如果不想要可以直接改用 DELETE 语句)
        db_execute('''
            UPDATE esims 
            SET is_used = 1, claimed_by = ?, claim_time = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (user_id, esim_id))
        
        # 增加用户领取次数
        db_execute('UPDATE users SET claimed_count = claimed_count + 1 WHERE user_id = ?', (user_id,))
        
    # 锁释放后发送激活码给用户
    await update.message.reply_text(
        f"🎉 <b>恭喜你！成功领取到一份 eSIM 激活码</b> 🎉\n\n"
        f"<code>{esim_code}</code>\n\n"
        f"<i>(点击激活码即可复制)</i>\n"
        f"请尽快激活使用哦！",
        parse_mode='HTML'
    )

# ================= 管理员功能 =================
@admin_only
async def toggle_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = db_execute('SELECT value FROM settings WHERE key = "is_active"', fetchone=True)[0]
    new_status = "0" if current == "1" else "1"
    db_execute('UPDATE settings SET value = ? WHERE key = "is_active"', (new_status,))
    
    status_text = "✅ 开启" if new_status == "1" else "🛑 关闭"
    await update.message.reply_text(f"领取功能当前状态已切换为：{status_text}")

@admin_only
async def add_esim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("使用方法: <code>/add_esim 激活码信息</code>\n可以一次发送多个，空格隔开，或者一次加一个。", parse_mode='HTML')
        return
        
    codes = context.args
    conn = sqlite3.connect('esim_bot.db')
    cursor = conn.cursor()
    for code in codes:
        cursor.execute('INSERT INTO esims (code) VALUES (?)', (code,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ 成功添加 {len(codes)} 个 eSIM 到数据库！")

@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("使用方法: <code>/ban 用户ID</code>", parse_mode='HTML')
        return
    target_id = context.args[0]
    db_execute('UPDATE users SET banned = 1 WHERE user_id = ?', (target_id,))
    await update.message.reply_text(f"✅ 已拉黑用户 {target_id}")

@admin_only
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("使用方法: <code>/unban 用户ID</code>", parse_mode='HTML')
        return
    target_id = context.args[0]
    db_execute('UPDATE users SET banned = 0 WHERE user_id = ?', (target_id,))
    await update.message.reply_text(f"✅ 已解封用户 {target_id}")

@admin_only
async def stock_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_unused = db_execute('SELECT count(*) FROM esims WHERE is_used = 0', fetchone=True)[0]
    total_used = db_execute('SELECT count(*) FROM esims WHERE is_used = 1', fetchone=True)[0]
    await update.message.reply_text(
        f"📊 <b>库存统计</b>\n\n"
        f"🟢 剩余可用：{total_unused}\n"
        f"🔴 已经被领：{total_used}",
        parse_mode='HTML'
    )

# ================= 启动逻辑 =================
def main():
    init_db()
    
    if BOT_TOKEN == "你的机器人的TOKEN":
        print("请先配置 BOT_TOKEN!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # 用户命令
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_esim", claim_esim))
    
    # 管理员命令
    application.add_handler(CommandHandler("toggle", toggle_bot))
    application.add_handler(CommandHandler("add_esim", add_esim))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("stats", stock_stats))

    # 消息处理 (用于口令验证)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 启动
    application.run_polling()

if __name__ == '__main__':
    main()
