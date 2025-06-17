# db.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import boto3
from botocore.exceptions import ClientError

def get_secret():

    secret_name = "klean/postgres"
    region_name = "us-east-2"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    secret = get_secret_value_response['SecretString']
    return secret

secret = get_secret()
DATABASE_URL = (
    f"postgresql+asyncpg://{secret['username']}:{secret['password']}@"
    f"{secret['host']}:{secret['port']}/{secret['dbname']}"
)


# Create the async engine
engine = create_async_engine(DATABASE_URL, echo=True, pool_size=10, max_overflow=20)

# Create session factory
async_session_maker = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Dependency for routes to get DB session
async def get_db():
    async with async_session_maker() as session:
        yield session


