from fastapi import FastAPI, HTTPException, File, UploadFile, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Dict
from fastapi.middleware.cors import CORSMiddleware
import httpx
from starlette.responses import JSONResponse
from gradio_client import Client
import easyocr
import shutil
import os
from PIL import Image
from db import get_db, engine
from types_1 import IngredientRequest, IngredientResponse, AskRequest, AskResponse, InputText, SafetyPercentageRequest, Ingredient
from utils import filter_unknown_chemicals
import boto3

app = FastAPI()

EC2_REGION = "us-west-2"
INSTANCE_ID = "i-0123456789abcdef0"  # Ollama GPU instance


reader = easyocr.Reader(['en'])

origins = [
    "http://localhost",  # Your local dev environment
    "https://*.ngrok.io",  # Allow any ngrok URL
    "https://903c-2601-646-8f00-f0e0-00-41be.ngrok-free.app/"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 🔓 Use ["http://localhost:19006"] for strict dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    print("App is starting up")

@app.on_event("shutdown")
async def on_shutdown():
    await engine.dispose()
    print("DB engine disposed and app shutdown cleanly")


@app.get("/start-ollama")
def start_ollama():
    ec2 = boto3.client("ec2", region_name=EC2_REGION)
    ec2.start_instances(InstanceIds=[INSTANCE_ID])
    return {"status": "Ollama instance started"}

@app.get("/stop-ollama")
def stop_ollama():
    ec2 = boto3.client("ec2", region_name=EC2_REGION)
    ec2.stop_instances(InstanceIds=[INSTANCE_ID])

# TODO: COMMENTED  AS OF NOW.-- look for other ways to do OCR 
@app.post("/ocr-api")
async def extract_text(file: UploadFile = File(...)):
    # Save the uploaded file temporarily
    print("Received file:", file)
    temp_file = f"temp_{file.filename}"
    
    with open(temp_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Reprocess via Pillow
        img = Image.open(temp_file)
        img = img.convert("RGB")
        img.save(temp_file, format="JPEG")

        # Check if OpenCV can read it
        import cv2
        if cv2.imread(temp_file) is None:
            raise ValueError("OpenCV failed to read image.")

        # OCR
        results = reader.readtext(temp_file)
        extracted = [item[1] for item in results]
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    return {"text": extracted}


@app.post("/safety-percentage")
def calculate_safety_percentage(payload: SafetyPercentageRequest):
    data = payload.payload
    total_known = len(data.known)

    if total_known == 0:
        raise HTTPException(status_code=400, detail="No known chemicals provided.")

    safe_chemicals = [chem for chem in data.known if chem.is_safe]
    unsafe_chemicals = [chem for chem in data.known if not chem.is_safe]

    safe_count = len(safe_chemicals)
    unsafe_count = len(unsafe_chemicals)
    safety_percentage = (safe_count / total_known) * 100

    # Build description based on safety percentage and unsafe chemicals
    if safety_percentage == 100:
        description = "All known chemicals are considered safe for use under normal conditions."
    elif safety_percentage >= 75:
        description = (
            f"Most known chemicals are safe. However, the following ingredient(s) "
            f"may pose safety concerns:\n" +
            "\n".join([f"- {chem.name}: {chem.description}" for chem in unsafe_chemicals])
        )
    elif safety_percentage >= 50:
        description = (
            f"A significant portion of the known chemicals are unsafe. Please review these ingredient(s):\n" +
            "\n".join([f"- {chem.name}: {chem.description}" for chem in unsafe_chemicals])
        )
    else:
        description = (
            f"Less than half of the known chemicals are safe. The composition may pose safety risks.\n"
            f"Unsafe ingredients:\n" +
            "\n".join([f"- {chem.name}: {chem.description}" for chem in unsafe_chemicals])
        )
    return {
        "total_chemicals": total_known,
        "safe_chemicals": safe_count,
        "unsafe_chemicals": total_known - safe_count,
        "safety_percentage": round(safety_percentage, 2),
        "description": description
    }


# Endpoint
@app.post("/check-ingredients", response_model=IngredientResponse)
async def check_ingredients(input_chemicals : IngredientRequest, db: AsyncSession = Depends(get_db)):

   
    normalized_input = [chem.lower() for chem in input_chemicals.ingredients]
  
    # with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        # placeholders = [f"%{chem.lower()}%" for chem in normalized_input]
    similar_knowns = set()
    known = []
    query = """
        SELECT id, name, is_safe, percentageifany, description, cases_where_harmful
        FROM ingredient_qwen
        WHERE similarity(name, %s) > 0.4
        ORDER BY similarity(name, %s) DESC
        LIMIT 1;
    """
    # input_chemical_name = "avobenzone 3%"  # Example input
    for chem in normalized_input:
        await db.execute(text(query), (chem, chem))
        result = db.fetchall()
        if result:
            similar_knowns.add(result['name'].lower())
            known.append(  {
        "id" : result['id'],
        "name": result['name'],
        "is_safe": result['is_safe'],
        "percentageifany": result['percentageifany'],
        "description": result['description'],
        "cases_where_harmful": result['cases_where_harmful']
    })

    known, unknown = filter_unknown_chemicals(normalized_input, similar_knowns, known)

    # cursor.close()
    # conn.close()

    return {
        "known": known,
        "unknown": unknown
    }




# Endpoint
@app.post("/ask", response_model=AskResponse)
async def ask_ollama(req: AskRequest):
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",
                    "prompt": req.question,
                    "stream": False
                }, 
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json' ,
                }
            )

            # print(response.text)
            response.raise_for_status()
        
            
            result = response.json()
            # print(result)
            return {"answer": result["response"]}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/ask-gemma", response_model=List[str])
async def ask_ollama(req: AskRequest):
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "gemma2:9b",
                    "prompt": req.question,
                    "stream": False
                }, 
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json' ,
                }
            )

            # print(response.text)
            response.raise_for_status()
        
            
            result = response.json()
            # print(result)
            return {"answer": result["response"]}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask-tinygemma", response_model=AskResponse)
async def ask_ollama(req: AskRequest):
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "gemma2:2b",
                    "prompt": req.question,
                    "stream": False
                }, 
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json' ,
                }
            )

            # print(response.text)
            response.raise_for_status()
        
            
            result = response.json()
            # print(result)
            return {"answer": result["response"]}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask-qwen", response_model=AskResponse)
async def ask_ollama(req: AskRequest):
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen3:8b",
                    "prompt": req.question,
                    "stream": False
                }, 
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json' ,
                }
            )

            # print(response.text)
            response.raise_for_status()
        
            
            result = response.json()
            # print(result)
            return {"answer": result["response"]}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/upload-ingredients")
async def upload_ingredients(unique_ingredients: List[Ingredient], db: AsyncSession = Depends(get_db)):
    
    print(unique_ingredients)

    inserted = []
    skipped = []

    for ingredient in unique_ingredients:
        ingredient_data = ingredient.model_dump()
        # print(ing)
        try:
            db.execute("SELECT 1 FROM ingredient WHERE LOWER(name) = LOWER(%s)", (ingredient_data["name"],))
            if db.fetchone():
                skipped.append(ingredient_data)
                continue


            # Insert the ingredient
            db.execute("""
                INSERT INTO ingredient (id, name, is_safe, percentageifany, description, cases_where_harmful)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                ingredient_data["id"],
                ingredient_data["name"],
                ingredient_data["is_safe"],
                ingredient_data["percentageifany"],
                ingredient_data["description"],
                ingredient_data["cases_where_harmful"]  # Python list is converted to PostgreSQL array
            ))
            inserted.append(ingredient_data)
        except Exception as e:
            print(f"Error inserting {ingredient_data}: {e}")
            continue

    # conn.commit()
    # cursor.close()
    # conn.close()

    return {
        "inserted_count": len(inserted),
        "skipped_existing": skipped
    }


@app.post("/upload-ingredients-gemma")
async def upload_ingredients(unique_ingredients: List[Ingredient], db: AsyncSession = Depends(get_db)):
    
    print(unique_ingredients)
    # ingredients_with_ids = enrich_ingredients_with_ids(unique_in:gredients)

    inserted = []
    skipped = []

    for ingredient in unique_ingredients:
        ingredient_data = ingredient.model_dump()
        # print(ing)
        try:
            db.execute("SELECT 1 FROM ingredient_gemma WHERE LOWER(name) = LOWER(%s)", (ingredient_data["name"],))
            if db.fetchone():
                skipped.append(ingredient_data)
                continue


            # Insert the ingredient
            db.execute("""
                INSERT INTO ingredient_gemma (id, name, is_safe, percentageifany, description, cases_where_harmful)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                ingredient_data["id"],
                ingredient_data["name"],
                ingredient_data["is_safe"],
                ingredient_data["percentageifany"],
                ingredient_data["description"],
                ingredient_data["cases_where_harmful"]  # Python list is converted to PostgreSQL array
            ))
            inserted.append(ingredient_data)
        except Exception as e:
            print(f"Error inserting {ingredient_data}: {e}")
            continue

    # conn.commit()
    # cursor.close()
    # conn.close()

    return {
        "inserted_count": len(inserted),
        "skipped_existing": skipped
    }


@app.post("/upload-ingredients-qwen")
async def upload_ingredients(unique_ingredients: List[Ingredient], db: AsyncSession = Depends(get_db)):
    
    print(unique_ingredients)
    # ingredients_with_ids = enrich_ingredients_with_ids(unique_in:gredients)

    inserted = []
    skipped = []

    for ingredient in unique_ingredients:
        ingredient_data = ingredient.model_dump()
        # print(ing)
        try:
            db.execute("SELECT 1 FROM ingredient_qwen WHERE LOWER(name) = LOWER(%s)", (ingredient_data["name"],))
            if db.fetchone():
                skipped.append(ingredient_data)
                continue


            # Insert the ingredient
            db.execute("""
                INSERT INTO ingredient_qwen (id, name, is_safe, percentageifany, description, cases_where_harmful)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                ingredient_data["id"],
                ingredient_data["name"],
                ingredient_data["is_safe"],
                ingredient_data["percentageifany"],
                ingredient_data["description"],
                ingredient_data["cases_where_harmful"]  # Python list is converted to PostgreSQL array
            ))
            inserted.append(ingredient_data)
        except Exception as e:
            print(f"Error inserting {ingredient_data}: {e}")
            continue

    # conn.commit()
    # cursor.close()
    # conn.close()

    return {
        "inserted_count": len(inserted),
        "skipped_existing": skipped
    }



