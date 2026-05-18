import os
import telebot
import yt_dlp
import glob

# 텔레그램 봇 토큰 (BotFather에서 발급받은 토큰을 여기에 넣으세요)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "여기에_봇_토큰을_입력하세요")

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "안녕하세요! 헤르메스 엔지니어링 기반 yt-dlp 봇입니다. 🚀\n\n"
        "다운로드할 유튜브(또는 다른 지원 사이트) 영상의 URL을 보내주세요.\n"
        "(텔레그램 봇 정책상 50MB 이하의 영상만 전송 가능합니다.)"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    
    if not url.startswith("http"):
        bot.reply_to(message, "올바른 URL을 입력해주세요. (http... 로 시작)")
        return
        
    bot.reply_to(message, "영상을 확인 중입니다. 잠시만 기다려주세요... ⏳")
    
    # yt-dlp 설정 (50MB 이하의 mp4 파일 다운로드)
    ydl_opts = {
        'format': 'best[ext=mp4][filesize<50M]/best[filesize<50M]',
        'outtmpl': '%(id)s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 영상 정보 추출 및 다운로드
            info = ydl.extract_info(url, download=True)
            filename = f"{info['id']}.{info['ext']}"
            
            # 다운로드된 파일이 있는지 확인
            if os.path.exists(filename):
                bot.reply_to(message, "다운로드 완료! 텔레그램으로 전송 중입니다... 📤")
                with open(filename, 'rb') as video:
                    bot.send_video(message.chat.id, video, caption=info.get('title', ''))
                # 전송 후 파일 삭제
                os.remove(filename)
            else:
                bot.reply_to(message, "영상 크기가 50MB를 초과하여 텔레그램으로 보낼 수 없거나 다운로드에 실패했습니다. 😢")
                
    except Exception as e:
        bot.reply_to(message, f"오류가 발생했습니다:\n{str(e)}")

if __name__ == "__main__":
    if BOT_TOKEN == "여기에_봇_토큰을_입력하세요":
        print("에러: 봇 토큰이 설정되지 않았습니다. bot.py 파일을 열어 토큰을 입력해주세요!")
    else:
        print("헤르메스 yt-dlp 봇(개발 서버)이 실행 중입니다. 텔레그램에서 메시지를 보내보세요!")
        bot.polling(none_stop=True)
