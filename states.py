from aiogram.fsm.state import State, StatesGroup

class Profile(StatesGroup):
    weight = State()
    height = State()
    age = State()
    activity = State()
    city = State()

class Water(StatesGroup):
    amount = State()

class Food(StatesGroup):
    product = State()
    amount = State()

class Workout(StatesGroup):
    type = State()
    duration = State()