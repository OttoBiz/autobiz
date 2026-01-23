import pandas as pd
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.output_parsers.openai_functions import JsonOutputFunctionsParser
from langchain.schema import StrOutputParser
import json
from dotenv import load_dotenv

# load your credentials from .env file
load_dotenv()

prompt = """
You are a database manager that resolves conflict during integration of a company's database to your existing database schema 
for your company.

**YOUR COMPANY DB SCHEMA**
    id : product_id
    business_id :  id of the business
    product_name : name of the product
    product_description : description of the product
    product_category : category of the product
    price: price of the product
    items_in_stock : amount/ number of the product available in the user's inventory
    tags : tags that can be associated with the product
    others: contains any other/extra attribute of a product and its value in a JSON dictionary format

**FOREIGN BUSINESS DETAILS**
business_id: {business_id}
db_sample: {data_rows}

Given the above, take time to understand foreign business's db sample, extract its schema and then map the foreign business data schema to your 
company's database schema.
Return a JSON dictionary where the key is a column in your company's db schema and the value is a feature/column in the 
foreign business db sample schema.

Your response:
"""

prompt = PromptTemplate.from_template(prompt)
llm = ChatOpenAI(model="gpt-3.5-turbo",  temperature=0, streaming=False).bind(response_format={ "type": "json_object" })

chain = prompt | llm | StrOutputParser()


kemi_df = pd.read_csv("backend/tests/test_script/kemi_surprises.csv")
tesla_df = pd.read_csv("backend/tests/test_script/tesla_tech.csv")

# Convert the first 5 rows to a dictionary
kemi_dict = kemi_df.head(5).to_dict(orient='records')
    
# Convert the first 5 rows to a dictionary
tesla_dict = kemi_df.head(5).to_dict(orient='records')

# print(chain.invoke({"business_id": 5, "data_rows": kemi_dict}))
print(json.loads(chain.invoke({"business_id": 16, "data_rows": tesla_dict})))
