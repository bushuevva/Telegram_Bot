# Импорт необходимых библиотек
import os
import asyncpg  # Библиотека для работы с PostgreSQL
from aiogram import Bot, Dispatcher, types, F  # Основные компоненты aiogram
from aiogram.filters import Command  # Фильтр для обработки команд
from aiogram.fsm.context import FSMContext  # Контекст машины состояний
from aiogram.fsm.state import State, StatesGroup  # Классы для создания состояний
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton  # Типы сообщений и элементов интерфейса
from aiogram.utils.keyboard import ReplyKeyboardBuilder  # Построитель клавиатур
from dotenv import load_dotenv  # Для загрузки переменных окружения из .env
import asyncio  # Для асинхронной работы

# Загрузка переменных окружения из файла .env
load_dotenv()

# Конфигурационные параметры
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  
DB_CONFIG = {  
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres'),
    'database': os.getenv('DB_NAME', 'currency_bot'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

# Инициализация основных компонентов бота
bot = Bot(token=TOKEN) 
dp = Dispatcher() 

# Функция для создания пула подключений к базе данных
async def create_db_pool():
    return await asyncpg.create_pool(
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
        database=DB_CONFIG['database'],
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        min_size=5,   
        max_size=20  
    )

# Функция инициализации структуры базы данных
async def init_db(pool):
    async with pool.acquire() as conn:   
        # Создание таблицы для хранения валют
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS currencies (
                id SERIAL PRIMARY KEY,  # Автоинкрементируемый идентификатор
                currency_name VARCHAR(3) NOT NULL UNIQUE,  # Код валюты (3 символа)
                rate NUMERIC NOT NULL  # Курс к рублю
            )
        ''')
        
        # Создание таблицы для хранения администраторов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,  # Автоинкрементируемый идентификатор
                chat_id VARCHAR(20) NOT NULL UNIQUE  # Уникальный ID чата администратора
            )
        ''')

# Функция добавления первого администратора
async def add_first_admin(pool):
    async with pool.acquire() as conn:
        await conn.execute(
            'INSERT INTO admins (chat_id) VALUES ($1) ON CONFLICT (chat_id) DO NOTHING',
            '918034698'
        )

# Функция проверки прав администратора
async def is_admin(pool, chat_id: str) -> bool:
    async with pool.acquire() as conn:
        # Проверка наличия chat_id в таблице администраторов
        return await conn.fetchval(
            'SELECT 1 FROM admins WHERE chat_id = $1',
            chat_id
        ) is not None

# Класс для определения состояний конечного автомата (FSM)
class CurrencyStates(StatesGroup):
    waiting_for_currency = State()          
    waiting_for_rate = State()              
    waiting_for_convert_currency = State()  
    waiting_for_convert_amount = State()    
    waiting_for_manage_action = State()      
    waiting_for_add_currency = State()      
    waiting_for_add_rate = State()          
    waiting_for_delete_currency = State()    
    waiting_for_update_currency = State()   
    waiting_for_update_rate = State()       

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message, pool: asyncpg.Pool):
    greeting = (
        "Привет! Я бот для работы с валютами.\n"
        "Мой создатель - студентка группы ФБИ-24 Бушуева Ирина\n\n"
    )
    
    # Проверка прав администратора и добавление соответствующих команд
    if await is_admin(pool, str(message.chat.id)):
        greeting += (
            "Команды администратора:\n"
            "/manage_currency - Управление валютами\n"
            "/get_currencies - Показать курсы\n"
            "/convert - Конвертировать валюту\n"
            "/help - Список всех команд"
        )
    else:
        greeting += (
            "Доступные команды:\n"
            "/get_currencies - Показать курсы\n"
            "/convert - Конвертировать валюту\n"
            "/help - Список всех команд"
        )
    
    await message.answer(greeting)

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: Message, pool: asyncpg.Pool):
    # Формирование списка команд в зависимости от прав пользователя
    if await is_admin(pool, str(message.chat.id)):
        commands = [
            "/start - Начало работы",
            "/manage_currency - Управление валютами",
            "/get_currencies - Показать курсы",
            "/convert - Конвертировать валюту"
        ]
    else:
        commands = [
            "/start - Начало работы",
            "/get_currencies - Показать курсы",
            "/convert - Конвертировать валюту"
        ]
    
    await message.answer("Доступные команды:\n\n" + "\n".join(commands))

# Обработчик команды /get_currencies
@dp.message(Command("get_currencies"))
async def cmd_get_currencies(message: Message, pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        # Получение списка всех валют из базы данных
        currencies = await conn.fetch('SELECT currency_name, rate FROM currencies')
    
    if not currencies:
        await message.answer("Нет сохранённых валют")
    else:
        response = "Курсы валют:\n"
        for record in currencies:
            response += f"{record['currency_name']}: {round(record['rate'], 2)} RUB\n"
        await message.answer(response)

# Обработчик команды /save_currency
@dp.message(Command("save_currency"))
async def cmd_save_currency(message: Message, state: FSMContext):
    await message.answer("Введите название валюты (например, USD, EUR):")
    await state.set_state(CurrencyStates.waiting_for_currency)

# Обработчик состояния ожидания названия валюты
@dp.message(CurrencyStates.waiting_for_currency)
async def process_currency(message: Message, state: FSMContext, pool: asyncpg.Pool):
    currency = message.text.upper()
    if not currency.isalpha() or len(currency) != 3:
        await message.answer("Название валюты должно состоять из трех букв (например, EUR)")
        return
    
    # Проверка существования валюты в базе
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            'SELECT 1 FROM currencies WHERE currency_name = $1',
            currency
        )
    
    if exists:
        await message.answer("Данная валюта уже существует")
        await state.clear()
        return
    
    # Сохранение введенной валюты и переход к следующему состоянию
    await state.update_data(currency=currency)
    await message.answer(f"Введите курс {currency} к рублю:")
    await state.set_state(CurrencyStates.waiting_for_rate)

# Обработчик состояния ожидания курса валюты
@dp.message(CurrencyStates.waiting_for_rate)
async def process_rate(message: Message, state: FSMContext, pool: asyncpg.Pool):
    try:
        rate = float(message.text)
        data = await state.get_data()
        currency = data['currency']
        
        # Сохранение новой валюты в базе данных
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO currencies (currency_name, rate) VALUES ($1, $2)',
                currency, rate
            )
        
        await message.answer(f"{currency} = {rate} RUB\nВалюта успешно сохранена")
    except ValueError:
        await message.answer("Ошибка! Введите число для курса.")
        return
    
    await state.clear()

# Обработчик команды /convert
@dp.message(Command("convert"))
async def cmd_convert(message: Message, state: FSMContext, pool: asyncpg.Pool):
    # Получение списка доступных валют
    async with pool.acquire() as conn:
        currencies = await conn.fetch('SELECT currency_name FROM currencies')
    
    if not currencies:
        await message.answer("Нет курсов. Добавьте через /save_currency")
        return
    
    # Формирование списка валют и запрос выбора
    currency_list = [record['currency_name'] for record in currencies]
    await message.answer(
        f"Введите валюту для конвертации:\nДоступно: {', '.join(currency_list)}"
    )
    await state.set_state(CurrencyStates.waiting_for_convert_currency)

# Обработчик состояния ожидания выбора валюты для конвертации
@dp.message(CurrencyStates.waiting_for_convert_currency)
async def process_convert_currency(message: Message, state: FSMContext, pool: asyncpg.Pool):
    currency = message.text.upper()
    
    # Проверка существования валюты
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            'SELECT 1 FROM currencies WHERE currency_name = $1',
            currency
        )
    
    if not exists:
        await message.answer("Валюта не найдена. Пожалуйста, попробуйте ещё раз")
        return
    
    # Сохранение выбранной валюты и переход к следующему шагу
    await state.update_data(convert_currency=currency)
    await message.answer(f"Введите сумму в {currency}:")
    await state.set_state(CurrencyStates.waiting_for_convert_amount)

# Обработчик состояния ожидания суммы для конвертации
@dp.message(CurrencyStates.waiting_for_convert_amount)
async def process_convert_amount(message: Message, state: FSMContext, pool: asyncpg.Pool):
    try:
        amount = float(message.text)
        data = await state.get_data()
        currency = data['convert_currency']
        
        # Получение текущего курса из базы данных
        async with pool.acquire() as conn:
            rate = await conn.fetchval(
                'SELECT rate FROM currencies WHERE currency_name = $1',
                currency
            )
        
        # Расчет и вывод результата
        result = amount * rate
        await message.answer(
            f"{amount} {currency} = {round(result, 2)} RUB "
            f"(1 {currency} = {rate} RUB)"
        )
    except ValueError:
        await message.answer("Ошибка! Введите число.")
        return
    
    await state.clear()

# Обработчик команды /manage_currency (только для администраторов)
@dp.message(Command("manage_currency"))
async def cmd_manage_currency(message: Message, state: FSMContext, pool: asyncpg.Pool):
    # Проверка прав администратора
    if not await is_admin(pool, str(message.chat.id)):
        await message.answer("Нет доступа к команде")
        return
    
    # Создание клавиатуры с опциями управления
    builder = ReplyKeyboardBuilder()
    builder.add(
        KeyboardButton(text="Добавить валюту"),
        KeyboardButton(text="Удалить валюту"),
        KeyboardButton(text="Изменить курс валюты")
    )
    builder.adjust(3)  # Расположение кнопок в 3 колонки
    
    await message.answer(
        "Выберите действие:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )
    await state.set_state(CurrencyStates.waiting_for_manage_action)

# Обработчик выбора "Добавить валюту"
@dp.message(CurrencyStates.waiting_for_manage_action, F.text == "Добавить валюту")
async def add_currency_handler(message: Message, state: FSMContext):
    await message.answer("Введите название валюты:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(CurrencyStates.waiting_for_add_currency)

# Обработчик состояния добавления новой валюты
@dp.message(CurrencyStates.waiting_for_add_currency)
async def process_add_currency(message: Message, state: FSMContext, pool: asyncpg.Pool):
    currency = message.text.upper()
    # Валидация введенных данных
    if not currency.isalpha() or len(currency) != 3:
        await message.answer("Название валюты должно состоять из трех букв (например, EUR)")
        return
    
    # Проверка на существование валюты
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            'SELECT 1 FROM currencies WHERE currency_name = $1',
            currency
        )
    
    if exists:
        await message.answer("Данная валюта уже существует")
        await state.clear()
        return
    
    # Сохранение данных и переход к вводу курса
    await state.update_data(currency=currency)
    await message.answer(f"Введите курс {currency} к рублю:")
    await state.set_state(CurrencyStates.waiting_for_add_rate)

# Обработчик состояния ввода курса новой валюты
@dp.message(CurrencyStates.waiting_for_add_rate)
async def process_add_rate(message: Message, state: FSMContext, pool: asyncpg.Pool):
    try:
        rate = float(message.text)
        data = await state.get_data()
        currency = data['currency']
        
        # Сохранение новой валюты в базе данных
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO currencies (currency_name, rate) VALUES ($1, $2)',
                currency, rate
            )
        
        await message.answer(f"Валюта: {currency} успешно добавлена")
    except ValueError:
        await message.answer("Ошибка! Введите число для курса.")
        return
    
    await state.clear()

# Обработчик выбора "Удалить валюту"
@dp.message(CurrencyStates.waiting_for_manage_action, F.text == "Удалить валюту")
async def delete_currency_handler(message: Message, state: FSMContext):
    await message.answer("Введите название валюты:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(CurrencyStates.waiting_for_delete_currency)

# Обработчик состояния удаления валюты
@dp.message(CurrencyStates.waiting_for_delete_currency)
async def process_delete_currency(message: Message, state: FSMContext, pool: asyncpg.Pool):
    currency = message.text.upper()
    
    # Удаление валюты из базы данных
    async with pool.acquire() as conn:
        result = await conn.execute(
            'DELETE FROM currencies WHERE currency_name = $1',
            currency
        )
    
    # Проверка результата удаления
    if result == "DELETE 0":
        await message.answer("Валюта не найдена")
    else:
        await message.answer(f"Валюта {currency} успешно удалена")
    
    await state.clear()

# Обработчик выбора "Изменить курс валюты"
@dp.message(CurrencyStates.waiting_for_manage_action, F.text == "Изменить курс валюты")
async def update_currency_handler(message: Message, state: FSMContext):
    await message.answer("Введите название валюты:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(CurrencyStates.waiting_for_update_currency)

# Обработчик состояния выбора валюты для обновления
@dp.message(CurrencyStates.waiting_for_update_currency)
async def process_update_currency(message: Message, state: FSMContext, pool: asyncpg.Pool):
    currency = message.text.upper()
    
    # Проверка существования валюты
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            'SELECT 1 FROM currencies WHERE currency_name = $1',
            currency
        )
    
    if not exists:
        await message.answer("Валюта не найдена")
        await state.clear()
        return
    
    # Сохранение выбранной валюты и переход к вводу нового курса
    await state.update_data(currency=currency)
    await message.answer(f"Введите новый курс {currency} к рублю:")
    await state.set_state(CurrencyStates.waiting_for_update_rate)

# Обработчик состояния ввода нового курса
@dp.message(CurrencyStates.waiting_for_update_rate)
async def process_update_rate(message: Message, state: FSMContext, pool: asyncpg.Pool):
    try:
        rate = float(message.text)
        data = await state.get_data()
        currency = data['currency']
        
        # Обновление курса в базе данных
        async with pool.acquire() as conn:
            await conn.execute(
                'UPDATE currencies SET rate = $1 WHERE currency_name = $2',
                rate, currency
            )
        
        await message.answer(f"Курс валюты {currency} успешно изменён на {rate} RUB")
    except ValueError:
        await message.answer("Ошибка! Введите число для курса.")
        return
    
    await state.clear()

# Основная функция запуска бота
async def main():
    pool = await create_db_pool()
    
    # Инициализация структуры базы данных
    await init_db(pool)
    await add_first_admin(pool)
    
    # Регистрация middleware для доступа к базе данных
    dp.update.middleware.register(DatabaseMiddleware(pool))
    
    print("Бот запущен...")
    # Запуск процесса опроса серверов Telegram
    await dp.start_polling(bot)

# Middleware для предоставления доступа к базе данных
class DatabaseMiddleware:
    def __init__(self, pool):
        self.pool = pool

    async def __call__(self, handler, event, data):
        data['pool'] = self.pool
        return await handler(event, data)

# Точка входа в приложение
if __name__ == '__main__':
    asyncio.run(main())