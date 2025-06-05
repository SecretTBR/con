import os
import subprocess
import zipfile
import shutil
import asyncio
import concurrent.futures
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.markdown import hbold

API_TOKEN = '7561245257:AAGV2IDHM8F_zuy7I2zVy9dUfi43-pss1uE' #Замените на токен вашего бота

#by kotek and HECODEP

bot = Bot(API_TOKEN)
dp = Dispatcher()

TEMP_DIR = 'temp_files'
os.makedirs(TEMP_DIR, exist_ok=True)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PVR_TOOL_PATH = os.path.join(CURRENT_DIR, "PVRTexToolCLI.exe")

executor = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() * 2)

user_locks = {}
user_converting = {}

PVR_TOOL_FORMAT = "ASTC_4X4,UBN,sRGB"

@dp.message(CommandStart())
async def start(message: types.Message):
    user_nick = message.from_user.username if message.from_user.username else message.from_user.first_name

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="BTX в PNG", callback_data="btx_to_png"),
            InlineKeyboardButton(text="PNG в BTX", callback_data="png_to_btx")
        ],
        [
            InlineKeyboardButton(text="ZIP BTX в ZIP PNG", callback_data="zip_btx_to_png"),
            InlineKeyboardButton(text="ZIP PNG в ZIP BTX", callback_data="zip_png_to_btx")
        ]
    ])

    await message.answer(f"*Йоу, {user_nick}! Выбери действие:*", reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(F.data.in_(["btx_to_png", "png_to_btx", "zip_btx_to_png", "zip_png_to_btx"]))
async def process_callback(callback_query: types.CallbackQuery):
    action = callback_query.data
    
    if action == "btx_to_png":
        await callback_query.message.answer("*Отправь мне .btx файл для конвертации в .png*", parse_mode="Markdown")
    elif action == "png_to_btx":
        await callback_query.message.answer("*Отправь мне .png файл для конвертации в .btx*", parse_mode="Markdown")
    elif action == "zip_btx_to_png":
        await callback_query.message.answer("*Отправь мне .zip архив с .btx файлами для конвертации в .png*", parse_mode="Markdown")
    elif action == "zip_png_to_btx":
        await callback_query.message.answer("*Отправь мне .zip архив с .png файлами для конвертации в .btx*", parse_mode="Markdown")
    
    await callback_query.answer()

@dp.message(F.document)
async def handle_document(message: types.Message):
    user_id = message.from_user.id

    if user_id in user_converting:
        try:
            await message.reply("*Подождите, сейчас идет конвертация вашего предыдущего файла...*", parse_mode="Markdown")
        except Exception as e:
            print(f"Error replying to user {user_id}: {e}")
        return

    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()

    async with user_locks[user_id]:
        user_converting[user_id] = message.message_id
        try:
            file_id = message.document.file_id
            file_info = await bot.get_file(file_id)
            file_path = file_info.file_path
            file_extension = os.path.splitext(message.document.file_name)[1].lower()
            original_name = os.path.splitext(message.document.file_name)[0]

            if file_extension not in ['.png', '.btx', '.zip']:
                await message.reply("*Йоу, отправь файл с расширением :* \n*.btx*\n*.png*\n*.zip*", parse_mode="Markdown")
                return

            converting_message = await message.reply("*⌛ Конвертирую твои файлы. Подожди немного...*", parse_mode="Markdown")  
            converting_message_id = converting_message.message_id

            input_path = os.path.join(TEMP_DIR, message.document.file_name)
            try:
                await bot.download_file(file_path, input_path)

                if not await is_valid_file(input_path, file_extension):
                    try:
                        await bot.delete_message(chat_id=message.chat.id, message_id=converting_message_id)
                    except Exception as e:
                        print(f"Error deleting message: {e}")
                    await message.reply("*❌ Этот файл не поддерживается!\nВозможно он поврежден или не соответствует формату.*", parse_mode="Markdown")
                    return

                output_path = None
                try:
                    if file_extension == '.png':
                        output_path = await run_in_executor(convert_png_to_btx, input_path)
                    elif file_extension == '.btx':
                        output_path = await run_in_executor(convert_btx_to_png, input_path, original_name)
                    elif file_extension == '.zip':
                        output_path = await process_zip(message, input_path)
                    else:
                        await message.reply("*Формат файла не поддерживается.*", parse_mode="Markdown")
                        return

                    if output_path:
                        try:
                            with open(output_path, 'rb') as f:
                                await bot.send_document(
                                    chat_id=message.chat.id,
                                    document=BufferedInputFile(f.read(), filename=os.path.basename(output_path)),
                                    caption="*Держи свои файлы!*", parse_mode="Markdown"
                                )
                        except Exception as e:
                            await message.reply(f"*Ошибка при отправке документа: {e}*", parse_mode="Markdown")

                except Exception as e:
                    await message.reply(f"*Ошибка обработки файла: {e}*", parse_mode="Markdown")
                finally:
                    try:
                        await bot.delete_message(chat_id=message.chat.id, message_id=converting_message_id)
                    except Exception as e:
                        print(f"Error deleting message: {e}")

                    await cleanup_files(input_path, output_path)

            except Exception as e:
                await message.reply(f"*Ошибка при скачивании файла: {e}*", parse_mode="Markdown")
                try:
                    await bot.delete_message(chat_id=message.chat.id, message_id=converting_message_id)
                except Exception as e:
                    print(f"Error deleting message: {e}")
        finally:
            if user_id in user_converting:
                del user_converting[user_id]

async def cleanup_files(input_path: str, output_path: str):
    try:
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
    except Exception as e:
        print(f"Error cleaning up files: {e}")

async def run_in_executor(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

async def process_zip(message: types.Message, input_path):
    original_name = os.path.splitext(os.path.basename(input_path))[0]
    output_zip = os.path.join(TEMP_DIR, f"{original_name}_convert.zip")
    temp_extract_dir = os.path.join(TEMP_DIR, f"extracted_{message.from_user.id}")
    
    try:
        os.makedirs(temp_extract_dir, exist_ok=True)
        
        try:
            with zipfile.ZipFile(input_path, 'r') as zip_ref:
                await run_in_executor(zip_ref.extractall, temp_extract_dir)
        except zipfile.BadZipFile as e:
            print(f"Bad Zip File: {e}")
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            await message.reply("*❌ Этот файл не поддерживается!\nВозможно он поврежден или не соответствует формату.*", parse_mode="Markdown")
            return None

        files_to_convert = []
        for root, _, files in os.walk(temp_extract_dir):
            for file in files:
                file_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                if ext in ('.png', '.btx'):
                    file_original_name = os.path.splitext(file)[0]
                    files_to_convert.append((file_path, ext, file_original_name))

        if not files_to_convert:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            await message.reply("*❌ В архиве не найдено подходящих файлов для конвертации (.png или .btx).*", parse_mode="Markdown")
            return None

        converted_files = []
        for file_path, ext, file_original_name in files_to_convert:
            converted_file = await run_in_executor(convert_file, file_path, ext, file_original_name)
            if converted_file:
                converted_files.append(converted_file)

        if not converted_files:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            await message.reply("*❌ Не удалось конвертировать ни один файл из архива.*", parse_mode="Markdown")
            return None

        await run_in_executor(create_zip, output_zip, converted_files)
        
        return output_zip

    except Exception as e:
        print(f"Error processing zip: {e}")
        await message.reply("*❌ Ошибка при обработке архива.*", parse_mode="Markdown")
        return None
    finally:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir, ignore_errors=True)

def convert_file(file_path, ext, original_name=None):
    try:
        if ext == '.png':
            return convert_png_to_btx(file_path)
        elif ext == '.btx':
            return convert_btx_to_png(file_path, original_name)
        else:
            return None
    except Exception as e:
        print(f"Error converting {file_path}: {e}")
        return None

def create_zip(output_zip, output_files):
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zip_out:
        for file in output_files:
            if file and os.path.exists(file):
                zip_out.write(file, os.path.basename(file))
                try:
                    os.remove(file)
                except Exception as e:
                    print(f"Error removing file {file}: {e}")

def convert_btx_to_png(input_path, original_name=None):
    if not original_name:
        file_name = os.path.splitext(os.path.basename(input_path))[0]
    else:
        file_name = original_name

    temp_ktx = os.path.join(TEMP_DIR, f"{file_name}_{os.urandom(4).hex()}.ktx")
    temp_pvr = os.path.join(TEMP_DIR, f"{file_name}_{os.urandom(4).hex()}.pvr")
    output_png = os.path.join(TEMP_DIR, f"{file_name}.png")

    try:
        with open(input_path, 'rb') as f_input, open(temp_ktx, 'wb') as f_output:
            f_input.seek(4)
            f_output.write(f_input.read())

        command = f'wine "{PVR_TOOL_PATH}" -i "{temp_ktx}" -o "{temp_pvr}" -d "{output_png}"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Ошибка PVRTexToolCLI: {result.stderr}")

        if not os.path.exists(output_png):
            raise Exception("PNG не создан")

        return output_png
    except Exception as e:
        print(f"Error converting {input_path}: {e}")
        return None
    finally:
        if os.path.exists(temp_ktx):
            try:
                os.remove(temp_ktx)
            except:
                pass
        if os.path.exists(temp_pvr):
            try:
                os.remove(temp_pvr)
            except:
              