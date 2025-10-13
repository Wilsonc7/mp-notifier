# MP Notifier (Render)

Servidor Flask gratuito en Render para recibir webhooks de Mercado Pago y consultar pagos recientes cada 20 segundos.

## Configuración en Render
1. Crear un nuevo **Web Service**.
2. Conectar este repositorio.
3. Configurar:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`
4. Agregar tu **Access Token** en el archivo `server.py`.
5. Una vez desplegado, usar la URL de Render (por ej. `https://mp-notifier.onrender.com/webhook`) en la configuración de **Webhooks** de tu app de Mercado Pago.
