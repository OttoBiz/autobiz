# from langchain_core.
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)  # PromptTemplate,
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.db.db_utils import *
from ..prompts.product_agent_prompt import *
from .function_args_schema import ProductInfoEvaluationOutput
from langchain_core.output_parsers import StrOutputParser
# from langchain.output_parsers.openai_functions import StrOJsonOutputFunctionsParser
from .tools import *
from langchain_core.utils.function_calling import convert_to_openai_tool
import json



#### Funtionality of the product agent
#1. Answer enquiries concerning product availabiility, price, product attributes or similar products.
#2. Provide bank details or payment links when customers are ready to buy a product.

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0) #, streaming=True)

product_evaluator = llm.bind(
    tools=[convert_to_openai_tool(ProductInfoEvaluationOutput)]
)

# print(tavily_tool.invoke("who is micheal jackson?"))

system_message = SystemMessagePromptTemplate.from_template(system_prompt)
rule_system_message = SystemMessagePromptTemplate.from_template(rule_system_prompt)
human_message = HumanMessagePromptTemplate.from_template(human_prompt)
prompt = ChatPromptTemplate.from_messages(
    [
        system_message,
        human_message,
        rule_system_message,
        # MessagesPlaceholder("agent_scratchpad"),
    ]
)

system_message = SystemMessagePromptTemplate.from_template(product_evaluation_prompt)
evaluator_prompt = ChatPromptTemplate.from_messages(
    [
        system_message
    ]
)

# Define evaluator chain
evaluator_chain = evaluator_prompt | product_evaluator #|JsonOutputFunctionsParser()

# Create an product agent
product_agent = prompt | llm | StrOutputParser() 


async def run_product_agent(
    customer_message,
    product_name,
    product_category,
    intent,
    tone,
    user_state,
    instruction=None,
    product_attributes=None,
    **kwargs
):
    # Get relevant products from database.
    """ 
    A user state is used to hold all information related to a customer including all products currently enquired about or being bought.
    Since a user can interact with different businesses at once and also interact with different products for any given business, 
    we use a combination of user id and business id as the key to the user_state as follows:
    user_id:business_id

    The structure of the value (user_state) of this key is given below:
    user_state ==  { 
                        products: {
                            product1 :{
                                retrieved_result (from database): List[str] list of products
                                db_queried: bool
                                available_products : List[str] of products
                            },
                            product2: {
                                retrieved_result (from database): List[str] list of products
                                db_queried: bool
                                available_products : List[str] of products
                            }
                        },
                        business_information:{
                            business_name: 
                            acc_name : 
                            acc_number:
                        },
                        chat_history:{}
    }
    """
    print("Customer's message: ", customer_message)
    
    # if a product was actually enquired.
    if product_name != "NONE":
        # Retrieve all product details if it exists in cache (already been discussed before)
        products = user_state.get("products", {})
        product = products.get(product_name, {})
        
        # Fetch products that were previously retrieved from the database for this index product if exists
        retrieved_products_info = product.get("retrieved_results", None)
        
        db_queried = product.get("db_queried", False)
        # print("Product name: ", product_name)
        # print("category: ", product_category)
        
        # if this is a new product (never been retrieved from db before), get items from db
        if retrieved_products_info is None and not db_queried:
            retrieved_products_info = await get_products(product_name, product_category, **kwargs )
            # products["product_name"] = product_name
            # print("Products: ", products)
            # print("Retrieved products: ", retrieved_products_info)
            product = {}
            product["retrieved_results"]= retrieved_products_info
            products["db_queried"] = True
            user_state["products"][product_name] = product
        
        # Use evaluator to determine if enquired product matches any product in the retrieved products
        result_match = product.get("result_match", None)
        if not result_match:
            result_match = await evaluator_chain.ainvoke({
                "available_products": retrieved_products_info,
                "customer_enquiry": customer_message
            })
            
            print("Retrieved products info: ", retrieved_products_info)

            # Retrieve output of the evaluator chain
            result_match = json.loads(result_match.additional_kwargs.get("tool_calls")[0].get("function")["arguments"])
            print("Result match: ", result_match)
            
        
        # if the customer's intent is to purchase or there were items retrieved, get business account details.
        # TODO: change the conditional statement.
        if intent== "purchase" or len(retrieved_products_info) > 1:
            business_information = user_state.get("business_information")
            print("Business information: ", business_information)
            bank_details = f"Bank name: {business_information['bank_name']}, Bank account name: {business_information['bank_account_name']}, Bank account number: {business_information['bank_account_number']}."
            print(bank_details)
        else:
            bank_details = ""
            
        # prepare inputs for product agent. 
        chain_input = {
                "vendor_bank_details": bank_details, #TODO: add account or payment details to businesses.
                "customer_message": customer_message,
                # "product_name": product_name,
                "product_category": product_category, # might not neeed this.
                "intent": intent,
                "tone": tone,
                "product_attributes": product_attributes,
                "instruction" : f"Further instructions concerning user: {result_match['instruction']}" if result_match["product_match"] != "NO_MATCH" and result_match.get("available_products") else ""
                
            }
        
        # print("Result match: " , result_match)
        
        # put in available product into input, if no available product, inform product agent that product is not available.
        # We might have to upsell here instead.'
        
        # Add result match to product cache.
        user_state["products"][product_name]['result_match'] = result_match
        
        # Get available products
        available_products = result_match.get("available_products", None)
        
        if available_products is not None:
            chain_input["available_products"] = available_products
        else:
            chain_input["available_products"] = "NO PRODUCT IS AVAILABLE CURRENTLY"
            
        # print(chain_input)
        return await product_agent.ainvoke(
            chain_input
        ), user_state
        
    else: # Else inform user that no product was specified and one needs to be specified.
        chain_input = {
                "vendor_bank_details": "", #TODO: add account or payment details to businesses.
                "customer_message": customer_message,
                # "product_name": product_name,
                "product_category": "",
                "intent": "",
                "tone": "",
                "product_attributes": "",
                "instruction" : f"Further instructions: Politely ask user to provide information about the name of the product he is interested in"                
            }
        
        # print("Result match: " , result_match)
        chain_input["available_products"] =  "NO PRODUCT WAS MENTIONED IN THE customer_message" 
        
        return product_agent.invoke(chain_input), user_state
