from time import sleep
import json
import network
import machine
import ubinascii
import secrets
from machine import Timer
import _thread

try:
    from umqtt.robust import MQTTClient
except ImportError:
    print("Installing missing dependencies")
    import mip
    mip.install("umqtt.simple")
    mip.install("umqtt.robust")
    from umqtt.robust import MQTTClient

__APPLICATION_NAME__ = "micropython-agent"
__VERSION__ = "0.0.1"


# Device info
serial_no = ubinascii.hexlify(machine.unique_id()).decode()
device_id = f"rpi-pico-{serial_no}"
topic_identifier = f"te/device/{device_id}//"

# Device in/out
adcpin = 4
sensor = machine.ADC(adcpin)
led = machine.Pin("LED", machine.Pin.OUT)


# MQTT Client (used to connect to thin-edge.io)
mqtt_client = f"{topic_identifier}#micropy2"
mqtt_broker = "roger.local"
mqtt_broker_port = 1883
mqtt = MQTTClient(mqtt_client, mqtt_broker, mqtt_broker_port, ssl=False)
mqtt.DEBUG = True

# Last Will and Testament message in case of unexpected disconnects
mqtt.lw_topic = f"{topic_identifier}/e/disconnected"
mqtt.lw_msg = json.dumps({"text": "Disconnected"})
mqtt.lw_qos = 1
mqtt.lw_retain = False

is_restarting = False


def read_temperature():
    adc_value = sensor.read_u16()
    volt = (3.3/65535) * adc_value
    temperature = 27 - (volt - 0.706)/0.001721
    return round(temperature, 1)

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
    while wlan.isconnected() == False:
        print('Waiting for connection..')
        sleep(1)
    ip = wlan.ifconfig()[0]
    print(f'Connected on {ip}')
    return ip

def blink_led(times=6, rate=0.1):
    for i in range(0, times):
        led.toggle()
        sleep(rate)
    led.on()

def on_message(topic, msg):
    print("Received command")
    if not len(msg):
        return

    global is_restarting
    global led
    global mqtt
    
    if is_restarting:
        print("Waiting for device to restart")
        return

    command_type = topic.decode("utf-8").split("/")[-2]
    message = json.loads(msg.decode("utf-8"))
    print(f"Received command: type={command_type}, topic={topic}, message={message}")
    #return
    
    if command_type == "restart":
        if message["status"] == "init":
            is_restarting = True
            led.off()
            state = {
                "status": "executing",
            }
            mqtt.publish(topic, json.dumps(state), retain=True, qos=1)
            #sleep(3)
            print("Restarting device")
            #sleep(1)
            machine.reset()    # or hard reset via: machine.reset()
            sleep(10)
        elif message["status"] == "executing":
            state = {
                "status": "successful",
            }
            mqtt.publish(topic, json.dumps(state), retain=True, qos=1)
            #sleep(1)

    elif command_type == "firmware_update":
        print("Applying firmware update")
    elif command_type == "software_list":
        if message["status"] == "init":
            state = {
                "status": "successful",
                "currentSoftwareList": [
                    {"type": "", "modules":[
                        {"name": __APPLICATION_NAME__, "version": __VERSION__},
                    ]}
                ]
            }
            mqtt.publish(topic, json.dumps(state), retain=True, qos=1)
    else:
        print("Unsupported command")

def publish_telemetry(client):
    # global mqtt
    message = {
        "temp": read_temperature(),
    }
    print(f"Publishing telemetry data. {message}")
    client.publish(f"{topic_identifier}/m/environment", json.dumps(message), qos=1)
    #blink_led(2, 0.5)
    #sleep(10)


def periodic(client):
    while 1:
        try:
            publish_telemetry(client)
        except:
            pass
        sleep(10)
    #telemetry_timer = Timer()
    
    #telemetry_timer.init(period=10000, mode=Timer.PERIODIC, callback=publish_telemetry)

def mqtt_connect():
    print(f"Connecting to thin-edge.io broker: broker={mqtt_broker}:{mqtt_broker_port}, client_id={mqtt_client}")
    
    mqtt.connect()
    mqtt.set_callback(on_message)
    print("Connected to thin-edge.io broker")


    #_thread.start_new_thread(periodic, tuple(mqtt))
    
    # Register device
    mqtt.publish(f"{topic_identifier}", json.dumps({
        "@type": "child-device",
        "name": device_id,
        "type": "micropython",
    }), qos=1, retain=True)
    
    # Add hardware info
    mqtt.publish(f"{topic_identifier}/twin/c8y_Hardware", json.dumps({
        "serialNumber": serial_no,
        "model": "Raspberry Pi Pico W",
        "revision": "RP2040",
    }), qos=1, retain=True)

    # register support for commands
    mqtt.publish(f"{topic_identifier}/cmd/restart", b"{}", retain=True, qos=1)
    mqtt.publish(f"{topic_identifier}/cmd/software_update", b"{}", retain=True, qos=1)
    mqtt.publish(f"{topic_identifier}/cmd/software_list", b"{}", retain=True, qos=1)

    # Startup message
    mqtt.publish(f"{topic_identifier}/e/boot", json.dumps({"text": f"Application started. version={__VERSION__}"}), qos=1)
    
    # subscribe to commands
    mqtt.subscribe(f"{topic_identifier}/cmd/+/+")
    print("Subscribed to commands topic")
    
    # Give visual queue that the device booted up
    blink_led()
    
    timer2 = Timer()
    timer2.init(period=2000, mode=Timer.PERIODIC, callback=lambda t:print('Ich werden alle 2 Sekunden ausgeführt.'))

    while 1:
        try:
            print("looping")
            blink_led(2, 0.5)
            mqtt.wait_msg()   # blocking
            #mqtt.check_msg()   # non-blocking
            #publish_telemetry(mqtt)
            #sleep(10)
        except Exception as ex:
            print(f"Unexpected error: {ex}")
            
    # Publish telemetry data
    # while 1:
    #     message = {
    #         "temp": read_temperature(),
    #     }
    #     print(f"Publishing telemetry data. {message}")
    #     mqtt.publish(f"{topic_identifier}/m/environment", json.dumps(message), qos=1)
    #     blink_led(2, 0.5)
    #     sleep(10)

def main():
    print(f"Starting: device_id={device_id}, topic={topic_identifier}")
    connect_wifi()
    led.on()
    mqtt_connect()

if __name__ == "__main__":
    main()

