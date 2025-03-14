For this repo to work on docker (not orbstack), you need to :

- Have a ollama server running (will take a while to download):
	- `docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama`
	- `docker exec -it ollama ollama run llama3`


- run `docker-compose -f docker-compose.yml up` to boot up a first time the services (we'll use this to know the url)

- Copy `./.env.example` into `./.env` and change the value : 
	- `OLLAMA_URL` to your url (take the value from docker desktop)
	
- Copy `./frontent/.env.example` into `./frontend/.env` and change the value :
	- `NEXT_PUBLIC_API_URL` (take the value from docker desktop)

- run `docker-compose -f docker-compose.yml up  --force-recreate` to run the app for real this time

In order to switch between ChatGPT / OLLAMA, in the `./.env` file, you'll need to switch the `OLLAMA_ENABLED` boolean


