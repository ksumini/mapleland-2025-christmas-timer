# 🎄 2025 MapleLand Christmas Event Timer
메이플랜드 크리스마스 이벤트 **쿨타임\(1h / 3h\)** 을 Discord DM으로 알려주는 개인용 타이머 서비스입니다.</br></br>
> 번거로운 알람설정, 웹 페이지를 켜둘 필요 없이  
 퀘스트 완료 후 버튼 한 번만 누르면  
 쿨타임 후 Discord DM으로 알림을 받습니다.  

🔗 서비스 바로가기  
👉 http://mapleland.minit.dev/

## ✨ Why I Built This
['행복한 마을의 크리스마스 이벤트'](https://public.maple.land/2c7c7f18-aa00-80cb-b885-f22dc54f8b4e)를 진행하면서 다음과 같은 불편함을 느꼈습니다.
- 휴대폰 알람은 소리/진동이 커서 작업 중 방해가 됨
- 매번 쿨타임을 직접 계산해서 알람을 설정해야 함
- 기존 웹 타이머는 페이지를 계속 켜둬야 하고 PC ↔ 모바일을 바꾸면 상태가 사라짐
그래서 목표는 단순했습니다.  
> “한 번 눌러두면, 어떤 기기에서든 확인 가능하고 시간이 되면 Discord DM으로 알아서 알려주는 타이머”

## 🧭 How It Works (User Flow)
1. Discord로 로그인
2. 봇 초대 + 테스트 DM으로 알림 활성화
3. 퀘스트 완료 후 타이머 버튼 클릭
4. 쿨타임 종료 시 Discord DM 수신
5. 3~4를 반복

## 🖥️ Screenshots / Demo
<img width="1280" height="1014" alt="image" src="https://github.com/user-attachments/assets/c49b4e87-f19d-4d06-8547-34c189b69e36" />

### 🎥 사용 방법 영상
https://github.com/user-attachments/assets/d1f33eb9-0aaa-48de-a677-af1f8ca174c9


## 🏗️ Architecture (High-level)
```text
[ Browser ]
     |
     |  OAuth / API
     v
[ FastAPI Server ]
     |
     |  Service Role
     v
[ Supabase (Postgres) ]
     |
     |  Poller
     v
[ Discord API ]
     |
     v
[ User DM ]
```
- FastAPI: 웹 UI + API + 백그라운드 Pollerer
- Supabase(Postgres): 사용자/타이머 상태 저장
- Discord API: OAuth 로그인 + DM 전송

## 🗂️ Project Structure
```text
app/
├─ main.py                 # FastAPI app entry
├─ routes/
│  ├─ web.py               # Web UI routes
│  ├─ auth.py              # Discord OAuth
│  ├─ api.py               # Timer / Status APIs
├─ services/
│  ├─ discord.py           # Discord DM / OAuth logic
│  ├─ timer.py             # Timer domain logic
│  ├─ poller.py            # Background poller
├─ db/
│  ├─ client.py            # Supabase client
│  ├─ users.py             # discord_users table logic
│  ├─ timers.py            # user_timers table logic
templates/
└─ home.html               # Jinja2 template
static/
├─ app.js
└─ app.css
```

## 🔐 Security & RLS
- Supabase Row Level Security (RLS) 활성화
- anon, authenticated role의 직접 접근 차단
- 서버는 Service Role Key로만 DB 접근
- 클라이언트는 DB에 직접 접근하지 않음
