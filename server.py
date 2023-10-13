#!/usr/bin/python3.3

import asyncio, sqlite3, logging, uvicorn, random, json, time, base64, httpx, resend, asyncpg, os, cachetools, openai
from fastapi import FastAPI, Body, Header, Request, HTTPException
from pydantic import BaseModel
from starlette.responses import HTMLResponse, JSONResponse, Response, RedirectResponse, FileResponse
from datetime import datetime, timedelta
from cachetools import TTLCache
from asyncache import cached

app = FastAPI()

cache = cachetools.TTLCache(maxsize=100, ttl=240)
openai.api_key = os.environ.get('POSTGRES_URL')
########################## FUNCS ##########################

class DB_api:
	async def init(self):
		self.cur = await asyncpg.connect(
			user=os.environ.get("POSTGRES_USER"),
			password=os.environ.get("POSTGRES_PASSWORD"),
			database=os.environ.get("POSTGRES_DATABASE"),
			host=os.environ.get("POSTGRES_HOST"),
			port=5432,
			statement_cache_size=0
		)
		await self.cur.execute("""CREATE TABLE IF NOT EXISTS reports(
			id SERIAL PRIMARY KEY,
			location TEXT,
			timestamp BIGINT,
			report_data TEXT,
			reporter_data TEXT
		)""")
		await self.cur.execute("""CREATE TABLE IF NOT EXISTS middleware(
			id SERIAL PRIMARY KEY,
			user_ip TEXT,
			user_fingerprint TEXT,
			timestamp BIGINT
		)""")
	

	async def insert(self, data, table_name='reports'):
		if type(data) is list:
			async with self.cur.transaction() as transaction:
				for x in data:
					columns = ', '.join(x.keys())
					values = ', '.join([f'${i}' for i in range(1, len(x) + 1)])

					insert_query = f"INSERT INTO {table_name} ({columns}) VALUES ({values})"
					await self.cur.execute(insert_query, *x.values())
				await transaction.commit()
		else:
			columns = ', '.join(data.keys())
			values = ', '.join([f'${i}' for i in range(1, len(data) + 1)])

			insert_query = f"INSERT INTO {table_name} ({columns}) VALUES ({values})"
			await self.cur.execute(insert_query, *data.values())




async def render_html(path: str):
	return open(f"./pages/{path}",encoding='utf-8').read()



class dTP_Report(BaseModel):
	location: str
	ts: int

class dTP_GPT(BaseModel):
	query: str
	history: list = []

class dTP_Creds(BaseModel):
	login: str = ''
	email: str
	password: str


async def create_report(location: str, timestamp: int = int(time.time()), reporter_data: dict = {'user_ip': '127.0.0.1', 'user_fingerprint': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'}):
	try:
		db = DB_api()
		await db.init()
		await db.insert({'location':location, 'timestamp':timestamp, 'report_data':base64.b64encode(f'{location}:{timestamp}'.encode()).decode(), 'reporter_data':base64.b64encode(json.dumps(reporter_data).encode()).decode()})
		print(f'report created: {location}|{timestamp}')
	except Exception as e: raise e; return False
	return True


async def send_email(to_emails: list, subject: str, html: str):
	async with httpx.AsyncClient() as client:
		payload = {
			"from": "GoonTracker@goontracker.site",
			"to": to_emails,
			"subject": subject,
			"html": html
			}
		
		req = await client.post('https://api.resend.com/emails',
			headers={'Authorization': f'Bearer {os.environ.get("RESEND_API_KEY")}', 'Content-Type': 'application/json'},
			json=payload
			)

	return req.json()


######################### ROUTES #############################


@app.get("/")
async def homepage_REDIRECT(request: Request, response: Response):
	try:
		language = request.headers.get("Accept-Language")[:2].lower()
		if language in ['ru','uk','ua']:
			return RedirectResponse("/ru")
		else: 
			return RedirectResponse("/en")
	except: return RedirectResponse("/en")


@app.get("/ru")
async def homepage_RU(request: Request, response: Response):
	return HTMLResponse(await render_html('RU/index.html'))


@app.get("/en")
async def homepage_EN(request: Request, response: Response):
	return HTMLResponse(await render_html('EN/index.html'))


@app.get("/console")
async def console(request: Request, response: Response):
	return HTMLResponse(await render_html('console.html'))


@app.get("/.well-known/discord")
async def verif(request: Request, response: Response):
	return FileResponse('./.well-known/discord')


@app.get("/get_goons")
async def get_goons(request: Request, response: Response):
	try:
		db = DB_api()
		await db.init()
		return {'status': True, 'reports': await db.cur.fetch("SELECT location, timestamp, report_data FROM reports ORDER BY id DESC")}
	except: return {'status': False, 'message':'Иди нахуй'}


@app.get("/last_report")
async def last_report(request: Request, response: Response):
	try:
		db = DB_api()
		await db.init()
		return {'status': True, 'data': (await db.cur.fetchrow("SELECT location, timestamp, report_data FROM reports ORDER BY id DESC"))}
	except Exception as e:
		raise e
		return {'status': False, 'message':'Иди нахуй'}




@app.get("/gpt")
async def gpt(request: Request, response: Response):
	return HTMLResponse(await render_html('chatGPT.html'))

@app.post("/gpt/res")
async def gpt_res(data: dTP_GPT, request: Request, response: Response):
	try:
		q = data.query
		conf = data.history
		if cache.get(q) is None: cache[q] = {'end': False, 'answer': ''}
		
		else: await asyncio.sleep(1); _ = cache.get(q); return {'status': True, 'data': _['answer'], 'end': _['end']}


		asyncio.get_event_loop().create_task(gpt_response(q, conf))
		await asyncio.sleep(3)

		_ = cache.get(q)
		return {'status': True, 'data': _['answer'], 'end': _['end']}

	except Exception as e: return {'status': False, 'message': e}




@app.post("/send_report")
async def send_report(data: dTP_Report, request: Request, response: Response):
	if await create_report(data.location, data.ts, {'user_ip': request.client.host, 'user_fingerprint': request.headers.get("User-Agent")}):
		return {'status': True, 'data': {'location': data.location, 'timestamp': data.ts}}
	else:
		return {'status': False, 'message':'Иди нахуй'}


@app.post("/auth")
async def verification(data: dTP_Creds, request: Request, response: Response):
	json_ = await request.json()

	code = ''.join(str(random.randint(0, 9)) for _ in range(6))
	try:
		html = """<!DOCTYPE html>\n<html>\n<head>\n<meta charset="UTF-8">\n<title>Подтверждение адреса электронной почты</title>\n<style>\na {\ntext-decoration: none;\n}\n</style>\n</head>\n<body>\n<p>Ваш код: <strong>%s</strong>. Его можно использовать, чтобы подтвердить адрес электронной почты для входа в <a href="http://goontracker.site">GoonTracker</a>.</p>\n<p>Если Вы не запрашивали это сообщение, проигнорируйте его.</p>\n<p>С уважением, Команда <strong>GoonTracker</strong>.</p>\n</body>\n</html>"""%(code)
		req = await send_email([json_['email']], f"Ваш код - {code}", html)

		return {'status': True, 'id': req['id']}

	except Exception as e: logging.error(e); return {'status': False, 'message': 'Слишком частая отправка запросов'}
######################## MIDDLEWARE #######################
class openai_plowsidee:
	def __init__(self):
		self.alive = True
		self.response = ''

	async def create_conversation(self, question, conf=[]):
		conf.append({"role": "user", "content": question})
		last_resp = ''

		async for resp in await openai.ChatCompletion.acreate(model='gpt-3.5-turbo', messages=conf, max_tokens=2048, stream=True):
			if resp.choices[0].finish_reason != None: self.alive=False;break
			try:
				if resp.choices[0].delta.content != last_resp:
					self.response+=str(resp.choices[0].delta.content)
					last_resp = resp.choices[0].delta.content
			except:pass
		self.alive=False

async def gpt_response(q, conf = []):
	op = openai_plowsidee()
	asyncio.get_event_loop().create_task(op.create_conversation(q, conf))
	last_resp = 0

	while op.alive:
		if len(op.response) - last_resp > 10:
			answer = op.response
			last_resp = len(answer)
			cache[q]['answer'] = answer
		
		await asyncio.sleep(.5)

	cache[q] = {'end': True, 'answer': op.response}



async def check_report_limit(request: Request, db):
	user_ip = request.client.host
	user_fingerprint = request.headers.get("User-Agent")


	last_report = await db.cur.fetchrow("SELECT * FROM middleware WHERE user_ip = $1 and user_fingerprint = $2",user_ip,user_fingerprint)
	if last_report is not None:
		last_report_time = last_report['timestamp']
		time_difference = int(time.time()) - last_report_time

		if time_difference < 300:
			if 'ru' in str(request.headers.get("Referer")):
				raise HTTPException(status_code=429, detail="Вы можете отправить репорт не чаще одного раза в 5 минут")
			else:
				raise HTTPException(status_code=429, detail="You can send a report no more than once every 5 minutes")

		await db.cur.execute("UPDATE middleware SET (user_ip, user_fingerprint, timestamp) = ($1, $2, $3) WHERE user_ip = $1 and user_fingerprint = $2", user_ip, user_fingerprint, int(time.time()))
	else:
		await db.cur.execute("INSERT INTO middleware(user_ip, user_fingerprint, timestamp) VALUES ($1, $2, $3)", user_ip, user_fingerprint, int(time.time()))



@app.middleware("http")
async def add_custom_middleware(request: Request, call_next):
	start_time = int(time.time())
	if request.url.path == '/send_report':		#/send_report
		db = DB_api()
		await db.init()
		try:
			await check_report_limit(request, db)
		except HTTPException as exc:
			return JSONResponse(status_code=exc.status_code, content={'status':False,'message':exc.detail})
	response = await call_next(request)
	response.headers["X-Process-Time"] = str(int(time.time()) - start_time)
	return response


if __name__ == '__main__':
	uvicorn.run(app, host="192.168.0.13", port=5000)
