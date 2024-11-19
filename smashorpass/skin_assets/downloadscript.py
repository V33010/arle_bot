import requests

def download_image(url, save_path):
    try:
        # Send a GET request to the URL
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        
        # Write the content to a file
        with open(save_path, 'wb') as file:
            file.write(response.content)
        print(f"Image successfully downloaded: {save_path}")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

# if __name__ == "__main__":
#     # Example usage
#     url = "https://media.valorant-api.com/weaponskinchromas/faba53e8-49c3-b167-1787-5d8caedbc552/fullrender.png"
#     save_path = "valorant_image.png"
#     download_image(url, save_path)
