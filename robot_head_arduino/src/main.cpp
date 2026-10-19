#include <Arduino.h>
#include <Servo.h>

Servo servo1;
Servo servo3;

const uint8_t SERVO1_PIN = 9;
const uint8_t SERVO2_PIN = 6;

const uint8_t SERVO1_POT_PIN = A1;
const uint8_t SERVO3_POT_PIN = A2;

int servo1Center = 90;
int servo3Center = 90;

// Last accepted potentiometer readings
int lastPot1;
int lastPot3;

// Pot must move by at least this much before it controls the servo.
// Increase this if you still get jitter.
const int POT_CHANGE_THRESHOLD = 10;


// --------------------------------------------------
// Read potentiometer with a little averaging
// --------------------------------------------------

int readPot(uint8_t pin)
{
    long total = 0;

    for (int i = 0; i < 8; i++)
    {
        total += analogRead(pin);
    }

    return total / 8;
}


// --------------------------------------------------
// Convert logical command angle to actual servo angle
// --------------------------------------------------

int calibratedAngle(int logicalAngle, int center)
{
    int actualAngle = logicalAngle + (center - 90);

    return constrain(actualAngle, 0, 180);
}


// --------------------------------------------------
// Synchronize potentiometers
//
// This is important after a SERIAL command.
// It tells Arduino:
//
// "Whatever the pots are currently reading,
// consider that unchanged."
//
// Therefore they will NOT immediately override
// the serial command.
// --------------------------------------------------

void syncPotentiometers()
{
    lastPot1 = readPot(SERVO1_POT_PIN);
    lastPot3 = readPot(SERVO3_POT_PIN);
}


// --------------------------------------------------
// SETUP
// --------------------------------------------------

void setup()
{
    Serial.begin(115200);

    servo1.attach(SERVO1_PIN);
    servo3.attach(SERVO2_PIN);

    lastPot1 = readPot(SERVO1_POT_PIN);
    lastPot3 = readPot(SERVO3_POT_PIN);

    // A1 normal
    servo1Center = map(lastPot1, 0, 1023, 0, 180);

    // A2 has +25 degree offset
    servo3Center = map(lastPot3, 0, 1023, 0, 180) + 25;
    servo3Center = constrain(servo3Center, 0, 180);

    servo1.write(servo1Center);
    servo3.write(servo3Center);

    delay(500);

    Serial.println("READY");
    Serial.println("SERIAL commands have priority");
    Serial.println("A1 adjusts Servo 1 90-degree position");
    Serial.println("A2 adjusts Servo 3 90-degree position (+25 deg)");
    Serial.println("Command format: <servo> <angle>");
}


// --------------------------------------------------
// LOOP
// --------------------------------------------------

void loop()
{
    // ==================================================
    // 1. SERIAL HAS PRIORITY
    // ==================================================

    if (Serial.available() > 0)
    {
        String command = Serial.readStringUntil('\n');
        command.trim();

        int servoNumber;
        int angle;

        if (sscanf(command.c_str(), "%d %d",
                   &servoNumber, &angle) != 2)
        {
            Serial.println("ERROR: use '<servo> <angle>'");

            syncPotentiometers();
            return;
        }

        if (angle < 0 || angle > 180)
        {
            Serial.println("ERROR: angle must be 0-180");

            syncPotentiometers();
            return;
        }


        // ----------------------------------------------
        // Servo 1
        // ----------------------------------------------

        if (servoNumber == 1)
        {
            int actualAngle =
                calibratedAngle(angle, servo1Center);

            servo1.write(actualAngle);

            Serial.print("SERVO1 logical = ");
            Serial.print(angle);

            Serial.print(", physical = ");
            Serial.println(actualAngle);
        }


        // ----------------------------------------------
        // Servo 3
        // ----------------------------------------------

        else if (servoNumber == 3)
        {
            int actualAngle =
                calibratedAngle(angle, servo3Center);

            servo3.write(actualAngle);

            Serial.print("SERVO3 logical = ");
            Serial.print(angle);

            Serial.print(", physical = ");
            Serial.println(actualAngle);
        }

        else
        {
            Serial.println("ERROR: servo must be 1 or 3");
        }


        // VERY IMPORTANT:
        //
        // After the serial command, reset the pot
        // reference readings.
        //
        // The pots now have to actually MOVE before
        // they are allowed to control a servo again.
        syncPotentiometers();

        return;
    }


    // ==================================================
    // 2. POTENTIOMETERS ONLY ACT IF THEY ACTUALLY MOVE
    // ==================================================

    int pot1 = readPot(SERVO1_POT_PIN);
    int pot3 = readPot(SERVO3_POT_PIN);


    // --------------------------------------------------
    // A1 -> Servo 1
    // --------------------------------------------------

    if (abs(pot1 - lastPot1) >= POT_CHANGE_THRESHOLD)
    {
        lastPot1 = pot1;

        servo1Center =
            map(pot1, 0, 1023, 0, 180);

        servo1Center =
            constrain(servo1Center, 0, 180);

        // Pot movement means:
        // show where logical 90 degrees is.
        servo1.write(servo1Center);

        Serial.print("A1 MOVED -> SERVO1 90 position = ");
        Serial.println(servo1Center);
    }


    // --------------------------------------------------
    // A2 -> Servo 3
    // --------------------------------------------------

    if (abs(pot3 - lastPot3) >= POT_CHANGE_THRESHOLD)
    {
        lastPot3 = pot3;

        int potAngle =
            map(pot3, 0, 1023, 0, 180);

        // +25 degree offset
        servo3Center = potAngle + 25;

        servo3Center =
            constrain(servo3Center, 0, 180);

        // Pot movement means:
        // show where logical 90 degrees is.
        servo3.write(servo3Center);

        Serial.print("A2 MOVED -> SERVO3 90 position = ");
        Serial.println(servo3Center);
    }

    delay(5);
}