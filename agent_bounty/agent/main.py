import logging
from ace_client import AceDataCloud
from sap_wrapper import SynapseAgent
from x402_handler import X402PaymentHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_agent():
    logger.info("Initializing Agent...")
    ace = AceDataCloud()
    sap = SynapseAgent()
    x402 = X402PaymentHandler()

    # 1. Register on SAP
    sap.register()
    
    # 2. Trigger workflow
    trigger = sap.wait_for_trigger()
    
    # 3. Execution: 3+ Ace Data Cloud APIs
    data = ace.fetch_data(trigger)
    analysis = ace.analyze_data(data)
    prediction = ace.generate_inference(analysis)
    
    # 4. Payment: x402 workflow
    tx = x402.process_payment(prediction)
    
    # 5. Submit result
    sap.submit(tx)
    logger.info("Agent job completed.")

if __name__ == "__main__":
    run_agent()
