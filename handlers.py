import aiohttp
import asyncio
from datetime import datetime
from aiogram import Router
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from states import Profile, Food, Water, Workout
from config import OPENWEATHER_API_KEY, USDA_API_KEY
import matplotlib.pyplot as plt
import io

router = Router()
users = {}

# Справочник тренировок (ккал/мин)
WORKOUT_TYPES = {
    "бег": 10,
    "плавание": 8,
    "йога": 4,
    "ходьба": 3,
    "велосипед": 7,
    "тренировка": 8,
    "спорт": 7,
    "танцы": 6,
    "аэробика": 7,
    "пилатес": 5
}


# вспомогательные функции

async def get_weather(city: str) -> float | None:
    """Получаем температуру из OpenWeatherMap"""
    url = "http://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["main"]["temp"]
    except:
        pass
    return None

def calc_water_goal(weight, activity_min, temp):
    """Считаем норму воды: база + активность + погода"""
    base = weight * 30
    bonus_activity = (activity_min // 30) * 500
    bonus_weather = 500 if temp > 25 else 0
    return int(base + bonus_activity + bonus_weather)

def calc_calorie_goal(weight, height, age, activity_min):
    """Формула Миффлина-Сан Жеора"""
    bmr = 10 * weight + 6.25 * height - 5 * age + 5
    activity_factor = 1.2 + min(activity_min / 60 * 0.1, 0.5)
    return int(bmr * activity_factor)


# поиск данных о калорийности

async def search_openfoodfacts(product: str):
    """Поиск в OpenFoodFacts"""
    url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {"action": "process", "search_terms": product, "json": "true", "page_size": 1}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if products := data.get("products"):
                        p = products[0]
                        cal = p.get("nutriments", {}).get("energy-kcal_100g", 0)
                        if cal > 0:
                            return {
                                "name": p.get("product_name") or product,
                                "cal": cal,
                                "source": "OpenFoodFacts"
                            }
    except:
        pass
    return None

async def translate_ru_en(text: str) -> str | None:
    """Перевод через MyMemory API"""
    url = "https://api.mymemory.translated.net/get"
    params = {"q": text, "langpair": "ru|en"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["responseData"]["translatedText"].lower().strip()
    except:
        pass
    return None

async def search_usda(product: str):
    """Поиск в USDA с приоритетом 'сырых' продуктов"""
    if not USDA_API_KEY:
        return None
    
    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    params = {"query": product, "pageSize": 10, "api_key": USDA_API_KEY}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if foods := data.get("foods"):
                        foods_sorted = sorted(
                            foods,
                            key=lambda f: any(kw in f.get("description", "").lower() 
                                            for kw in ["raw", "fresh", "unprepared"]),
                            reverse=True
                        )
                        
                        for food in foods_sorted[:5]:
                            cal_value = 0
                            for nut in food.get("foodNutrients", []):
                                if nut.get("nutrientName") == "Energy" and nut.get("unitName") == "KCAL":
                                    cal_value = nut.get("value", 0)
                                    break
                            
                            if cal_value > 0:
                                return {
                                    "name": food.get("description", product),
                                    "cal": cal_value,
                                    "source": "USDA"
                                }
    except:
        pass
    return None

async def find_food_calories(query: str):
    """Поиск калорийности: сначала перевод, потом USDA, потом OpenFoodFacts"""
    en_query = None
    try:
        en_query = await asyncio.wait_for(translate_ru_en(query), timeout=8.0)
    except:
        pass
    
    if en_query:
        try:
            result = await asyncio.wait_for(search_usda(en_query), timeout=10.0)
            if result and result.get("cal", 0) > 0:
                result["orig"] = query
                result["trans"] = en_query
                return result
        except:
            pass
    
    try:
        result = await asyncio.wait_for(search_openfoodfacts(en_query or query), timeout=10.0)
        if result and result.get("cal", 0) > 0:
            return result
    except:
        pass
    
    return None


# обработчики команд

@router.message(Command("start"))
async def start_cmd(msg: Message):
    await msg.reply(
        "💧 Привет! Я помогу следить за водой и калориями.\n\n"
        "Сначала настрой профиль: /set_profile\n"
        "Справка: /help"
    )

@router.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.reply(
        "📚 СПРАВКА ПО КОМАНДАМ:\n\n"
        "/set_profile — настроить вес, рост, возраст, город и активность\n"
        "/log_water — записать выпитую воду\n"
        "/log_food — записать съеденный продукт\n"
        "/log_workout — записать тренировку\n"
        "/check — показать текущий прогресс по воде и калориям\n"
        "/graph_wat — график потребления воды за день\n"
        "/graph_cal — график баланса калорий за день"
    )

@router.message(Command("set_profile"))
async def set_profile_start(msg: Message, state: FSMContext):
    await state.set_state(Profile.weight)
    await msg.reply("Введи свой вес в кг (например, 75):\nСправка: /help")

@router.message(Profile.weight)
async def set_weight(msg: Message, state: FSMContext):
    try:
        weight = float(msg.text)
        if weight < 30 or weight > 200:
            raise ValueError
        await state.update_data(weight=weight)
        await state.set_state(Profile.height)
        await msg.reply("Теперь рост в см (например, 180):\nСправка: /help")
    except:
        await msg.reply("Напиши нормальный вес (30-200 кг):\nСправка: /help")

@router.message(Profile.height)
async def set_height(msg: Message, state: FSMContext):
    try:
        height = float(msg.text)
        if height < 100 or height > 250:
            raise ValueError
        await state.update_data(height=height)
        await state.set_state(Profile.age)
        await msg.reply("Сколько тебе лет?\nСправка: /help")
    except:
        await msg.reply("Рост должен быть 100-250 см:\nСправка: /help")

@router.message(Profile.age)
async def set_age(msg: Message, state: FSMContext):
    try:
        age = int(msg.text)
        if age < 10 or age > 100:
            raise ValueError
        await state.update_data(age=age)
        await state.set_state(Profile.activity)
        await msg.reply("Сколько минут активности в день?\nСправка: /help")
    except:
        await msg.reply("Возраст 10-100 лет:\nСправка: /help")

@router.message(Profile.activity)
async def set_activity(msg: Message, state: FSMContext):
    try:
        activity = int(msg.text)
        if activity < 0 or activity > 1440:
            raise ValueError
        await state.update_data(activity=activity)
        await state.set_state(Profile.city)
        await msg.reply("В каком городе живёшь?\nСправка: /help")
    except:
        await msg.reply("Активность 0-1440 минут:\nСправка: /help")

@router.message(Profile.city)
async def set_city(msg: Message, state: FSMContext):
    city = msg.text.strip()
    data = await state.get_data()
    
    temp = await get_weather(city)
    if temp is None:
        await msg.reply(f"Не нашёл город '{city}'. Попробуй 'Moscow'.\nСправка: /help")
        return
    
    water_goal = calc_water_goal(data['weight'], data['activity'], temp)
    calorie_goal = calc_calorie_goal(data['weight'], data['height'], data['age'], data['activity'])
    
    users[msg.from_user.id] = {
        "weight": data["weight"],
        "height": data["height"],
        "age": data["age"],
        "activity": data["activity"],
        "city": city,
        "temp": temp,
        "water_goal": water_goal,
        "calorie_goal": calorie_goal,
        "water": 0,
        "cal_eaten": 0,
        "cal_burned": 0,
        "water_log": [],
        "cal_log": []
    }
    
    await msg.reply(
        f"✅ Профиль готов!\n"
        f"🏙 {city}, {temp:.1f}°C\n"
        f"💧 Норма воды: {water_goal} мл\n"
        f"🔥 Норма калорий: {calorie_goal} ккал\n\n"
        f"Справка: /help"
    )
    await state.clear()

@router.message(Command("log_water"))
async def log_water_start(msg: Message, state: FSMContext):
    await state.set_state(Water.amount)
    await msg.reply("Сколько миллилитров воды вы выпили?\n(например: 250)\nСправка: /help")

@router.message(Water.amount)
async def log_water_amount(msg: Message, state: FSMContext):
    try:
        ml = float(msg.text)
        if ml <= 0:
            raise ValueError
        
        uid = msg.from_user.id
        if uid not in users:
            await msg.reply("Сначала настрой профиль через /set_profile.\nСправка: /help")
            await state.clear()
            return
        
        now = datetime.now()
        users[uid]["water"] += ml
        users[uid]["water_log"].append((now, ml))
        
        goal = users[uid]["water_goal"]
        left = max(0, goal - users[uid]["water"])
        pct = min(100, users[uid]["water"] / goal * 100)
        
        await msg.reply(
            f"💧 Записано: +{ml:.0f} мл\n"
            f"📊 Прогресс: {users[uid]['water']:.0f} / {goal} мл ({pct:.0f}%)\n"
            f"✅ Осталось допить: {left:.0f} мл\n\n"
            f"Справка: /help"
        )
        await state.clear()
    
    except:
        await msg.reply("Напиши число (мл):\nСправка: /help")

@router.message(Command("log_food"))
async def log_food_start(msg: Message, state: FSMContext):
    await state.set_state(Food.product)  # ← Устанавливаем состояние для продукта
    await msg.reply("Какой продукт вы съели?\n(например: банан, курица)\nСправка: /help")

@router.message(Food.product)
async def log_food_product(msg: Message, state: FSMContext):
    product = msg.text.strip()
    food = await find_food_calories(product)
    
    if not food:
        await msg.reply(
            f"Не нашёл '{product}'. Попробуй:\n"
            "• Английское название ('banana')\n"
            "• Проще ('хлеб' вместо 'ржаной хлеб')\n\n"
            f"Справка: /help"
        )
        return
    
    await state.update_data(food=food)
    src = food.get("source", "база")
    await state.set_state(Food.amount)
    await msg.reply(
        f"✅ {food['name']}\n"
        f"📊 {food['cal']} ккал на 100г ({src})\n"
        f"❓ Сколько грамм съели?\nСправка: /help"
    )

@router.message(Food.amount)
async def log_food_grams(msg: Message, state: FSMContext):
    try:
        grams = float(msg.text)
        if grams <= 0:
            raise ValueError
        
        data = await state.get_data()
        food = data.get("food")
        if not food:
            await msg.reply("Сначала выберите продукт через /log_food.\nСправка: /help")
            await state.clear()
            return
        
        calories = (grams / 100) * food["cal"]
        
        uid = msg.from_user.id
        if uid not in users:
            await msg.reply("Сначала настрой профиль через /set_profile.\nСправка: /help")
            await state.clear()
            return
        
        now = datetime.now()
        users[uid]["cal_eaten"] += calories
        users[uid]["cal_log"].append((now, calories, "food"))
        
        await msg.reply(
            f"✅ Записано: {calories:.0f} ккал ({grams:.0f}г {food['name']})\n"
            f"🔥 Всего сегодня: {users[uid]['cal_eaten']:.0f} ккал\n\n"
            f"Внести ещё? /log_food\n"
            f"Справка: /help"
        )
        await state.clear()
    
    except:
        await msg.reply("Напиши число (граммы):\nСправка: /help")

@router.message(Command("log_workout"))
async def log_workout_start(msg: Message, state: FSMContext):
    types_list = ", ".join(WORKOUT_TYPES.keys())
    await state.set_state(Workout.type)
    await msg.reply(
        f"Выберите тип тренировки:\n{types_list}\n\n"
        f"Или напишите свой (будет использован средний расход 5 ккал/мин)\n"
        f"Справка: /help"
    )

@router.message(Workout.type)
async def log_workout_type(msg: Message, state: FSMContext):
    wtype = msg.text.lower().strip()
    await state.update_data(wtype=wtype)
    await state.set_state(Workout.duration)
    await msg.reply(f"Сколько минут длилась тренировка '{wtype}'?\nСправка: /help")

@router.message(Workout.duration)
async def log_workout_duration(msg: Message, state: FSMContext):
    try:
        mins = int(msg.text)
        if mins <= 0:
            raise ValueError
        
        data = await state.get_data()
        wtype = data["wtype"]
        kcal_per_min = WORKOUT_TYPES.get(wtype, 5)
        
        burned = kcal_per_min * mins
        water_bonus = (mins // 30) * 200
        
        uid = msg.from_user.id
        if uid not in users:
            await msg.reply("Сначала настрой профиль.\nСправка: /help")
            await state.clear()
            return
        
        now = datetime.now()
        users[uid]["cal_burned"] += burned
        users[uid]["cal_log"].append((now, burned, "workout"))
        
        old_goal = users[uid]["water_goal"]
        users[uid]["water_goal"] += water_bonus
        
        await msg.reply(
            f"🏃 Тренировка: {wtype.capitalize()} ({mins} мин)\n"
            f"🔥 Сожжено калорий: {burned:.0f} ккал\n"
            f"💧 Норма воды увеличена на {water_bonus} мл\n"
            f"   (было: {old_goal} мл → стало: {users[uid]['water_goal']} мл)\n\n"
            f"Справка: /help"
        )
        await state.clear()
    
    except:
        await msg.reply("Напиши число (минуты):\nСправка: /help")

@router.message(Command("check"))
async def check_progress(msg: Message):
    uid = msg.from_user.id
    if uid not in users:
        await msg.reply("Сначала настрой профиль через /set_profile.\nСправка: /help")
        return
    
    u = users[uid]
    water_pct = min(100, u["water"] / u["water_goal"] * 100)
    cal_balance = u["cal_eaten"] - u["cal_burned"]
    cal_left = max(0, u["calorie_goal"] - cal_balance)
    
    # Рекомендация по калориям
    remaining = u["calorie_goal"] - cal_balance
    if remaining > 200:
        rec = f"💡 Можно съесть ещё ~{remaining:.0f} ккал"
    elif remaining > 0:
        rec = "💡 Почти достиг цели — можно лёгкий перекус"
    else:
        rec = "✅ Цель по калориям достигнута!"
    
    await msg.reply(
        f"📊 ПРОГРЕСС СЕГОДНЯ\n\n"
        f"💧 ВОДА:\n"
        f"Выпито: {u['water']:.0f} / {u['water_goal']} мл ({water_pct:.0f}%)\n"
        f"Осталось допить: {max(0, u['water_goal'] - u['water']):.0f} мл\n\n"
        f"🔥 КАЛОРИИ:\n"
        f"Съедено: {u['cal_eaten']:.0f} ккал\n"
        f"Сожжено: {u['cal_burned']:.0f} ккал\n"
        f"Баланс: {cal_balance:.0f} ккал из {u['calorie_goal']} ккал\n"
        f"До цели: {cal_left:.0f} ккал\n\n"
        f"{rec}\n\n"
        f"Справка: /help"
    )

@router.message(Command("graph_wat"))
async def show_water_graph(msg: Message):
    uid = msg.from_user.id
    if uid not in users:
        await msg.reply("Сначала настрой профиль через /set_profile.\nСправка: /help")
        return
    
    u = users[uid]
    logs = u["water_log"]
    
    # Создаём данные от 00:00 с нулевым значением
    if not logs:
        await msg.reply("Нет данных для графика. Сначала запиши воду через /log_water.\nСправка: /help")
        return
    
    # Сортируем логи по времени
    logs.sort(key=lambda x: x[0])
    
    # Добавляем точку 00:00 с нулевым значением
    day_start = logs[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    plot_times = [day_start]
    plot_values = [0.0]
    
    total = 0.0
    for ts, amount in logs:
        total += amount
        plot_times.append(ts)
        plot_values.append(total)
    
    # Форматируем временные метки
    time_labels = [t.strftime("%H:%M") for t in plot_times]
    
    # Строим график
    plt.figure(figsize=(10, 4))
    plt.plot(time_labels, plot_values, marker='o', linewidth=2, color='#1E88E5', label='Выпито')
    plt.axhline(y=u["water_goal"], color='green', linestyle='--', label=f'Цель: {u["water_goal"]} мл')
    plt.fill_between(range(len(plot_values)), plot_values, alpha=0.3, color='#1E88E5')
    
    plt.title(f'Потребление воды ({datetime.now().strftime("%d.%m")})')
    plt.xlabel('Время')
    plt.ylabel('мл')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.ylim(bottom=0)
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    await msg.reply_photo(
        BufferedInputFile(buf.read(), filename="water_graph.png"),
        caption=f"💧 Выпито: {u['water']:.0f} / {u['water_goal']} мл\nСправка: /help"
    )

@router.message(Command("graph_cal"))
async def show_calorie_graph(msg: Message):
    uid = msg.from_user.id
    if uid not in users:
        await msg.reply("Сначала настрой профиль через /set_profile.\nСправка: /help")
        return
    
    u = users[uid]
    logs = u["cal_log"]
    
    if not logs:
        await msg.reply("Нет данных для графика. Сначала запиши еду или тренировку.\nСправка: /help")
        return
    
    # Сортируем логи по времени
    logs.sort(key=lambda x: x[0])
    day_start = logs[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Разделяем потребление и сжигание
    eat_times, eat_values, total_eat = [day_start], [0.0], 0.0
    burn_times, burn_values, total_burn = [day_start], [0.0], 0.0
    
    for ts, value, typ in logs:
        if typ == "food":
            total_eat += value
            eat_times.append(ts)
            eat_values.append(total_eat)
        elif typ == "workout":
            total_burn += value
            burn_times.append(ts)
            burn_values.append(total_burn)
    
    # Форматируем временные метки
    eat_labels = [t.strftime("%H:%M") for t in eat_times]
    burn_labels = [t.strftime("%H:%M") for t in burn_times]
    
    # Строим график
    plt.figure(figsize=(10, 4))
    
    if len(eat_times) > 1:
        plt.plot(eat_labels, eat_values, marker='o', linewidth=2, color='#FB8C00', label='Съедено')
    
    if len(burn_times) > 1:
        plt.plot(burn_labels, [-v for v in burn_values], marker='s', linewidth=2, color='#E53935', label='Сожжено')
    
    plt.axhline(y=u["calorie_goal"], color='#43A047', linestyle='--', label=f'Цель: {u["calorie_goal"]} ккал')
    plt.axhspan(0, u["calorie_goal"], alpha=0.1, color='green')
    
    plt.title(f'Баланс калорий ({datetime.now().strftime("%d.%m")})')
    plt.xlabel('Время')
    plt.ylabel('ккал')
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.ylim(bottom=0)  # Начинаем с нуля по оси Y
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    balance = total_eat - total_burn
    status = "✅ В норме" if balance <= u["calorie_goal"] else "⚠️ Превышение"
    
    await msg.reply_photo(
        BufferedInputFile(buf.read(), filename="calorie_graph.png"),
        caption=f"🔥 Баланс: {balance:.0f} ккал из {u['calorie_goal']} ккал\n{status}\nСъедено: {total_eat:.0f} | Сожжено: {total_burn:.0f}\n\nСправка: /help"
    )