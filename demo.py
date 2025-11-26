from apify_client import ApifyClient

# Initialize the ApifyClient with your API token
client = ApifyClient("apify_api_q6zLdffUws1w5FInc1bUElmU1SPcYg3jI0Gd")

# Prepare the Actor input
run_input = { "startUrls": [
        { "url": "https://www.facebook.com/copperkettleyqr/" },
        { "url": "https://www.facebook.com/HiltonGardenInnMontrealAirport/" },
    ] }

# Run the Actor and wait for it to finish
run = client.actor("4Hv5RhChiaDk6iwad").call(run_input=run_input)

# Fetch and print Actor results from the run's dataset (if there are any)
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(item)