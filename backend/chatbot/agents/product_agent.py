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

evaluator_chain = evaluator_prompt | product_evaluator #|JsonOutputFunctionsParser()



# Create an agent executor by passing in the agent and tools
product_agent = prompt | llm | StrOutputParser() #AgentExecutor(agent=agent, tools=tools, verbose=True)


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
    """ user_state products key structure ==  { 
                                    products: {
                                    product1 :{
                                        retrieved_result (from database): List[str] list of products
                                        db_queried: bool
                                        available_products : List[str] of products
                                    },
                                    product1: {
                                        retrieved_result (from database): List[str] list of products
                                    }},
                                    business_information:{
                                        business_name: 
                                        acc_name : 
                                        acc_number:
                                    },
                                    chat_history:{}
    }
    """
    if product_name != "NONE":
        products = user_state.get("products", {})
        product = products.get(product_name, {})
        retrieved_products_info = product.get("retrieved_results", None)
        
        db_queried = product.get("db_queried", False)
        # print("Product name: ", product_name)
        # print("category: ", product_category)
        
        if retrieved_products_info is None and not db_queried:
            retrieved_products_info = await get_products(product_name, product_category, **kwargs )
            # products["product_name"] = product_name
            # print("Products: ", products)
            # print("Retrieved products: ", retrieved_products_info)
            products[product_name] = {}
            products[product_name]["retrieved_results"]= retrieved_products_info
            products[product_name]["db_queried"] = True
            user_state["products"] = products
        
        result_match = await evaluator_chain.ainvoke({
            "available_products": retrieved_products_info,
            "customer_enquiry": customer_message
        })
        
        print("Retrieved products info: ", retrieved_products_info)

        result_match = json.loads(result_match.additional_kwargs.get("tool_calls")[0].get("function")["arguments"])
        print("Result match: ", result_match)
        
        
        if intent== "purchase" or len(retrieved_products_info) > 1:
            business_information = user_state.get("business_information")
            print("Business information: ", business_information)
            bank_details = f"Bank name: {business_information['bank_name']}, Bank account name: {business_information['bank_account_name']}, Bank account number: {business_information['bank_account_number']}."
            print(bank_details)
        else:
            bank_details = ""
            
            
        chain_input = {
                "vendor_bank_details": bank_details, #TODO: add account or payment details to businesses.
                "customer_message": customer_message,
                # "product_name": product_name,
                "product_category": product_category,
                "intent": intent,
                "tone": tone,
                "product_attributes": product_attributes,
                "instruction" : f"Further instructions concerning user: {result_match['instruction']}" if result_match["product_match"] != "NO_MATCH" and result_match.get("available_products") else ""
                
            }
        
        # print("Result match: " , result_match)
        chain_input["available_products"] = result_match.get("available_products", "NO PRODUCT IS AVAILABLE CURRENTLY") 
        # print(chain_input)
        return await product_agent.ainvoke(
            chain_input
        ), user_state
        
    else:
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
