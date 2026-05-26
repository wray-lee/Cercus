#include <Arduino.h>

// ============================================================================
// Airflow Pump Speed Test Suite - Firmware
// Board: Arduino Mega 2560
// Protocol:
//   Activate:  <index,duration_ms>  or <index> (default 5000ms)
//   Stop:      <S,index>            or <index,0>
//   Response:  <ACK,idx,dur>  <DONE,idx>  <ERR,INVALID_INDEX>  <READY>
// ============================================================================

// -- Pin Configuration (8 Channels) --
static const uint8_t PUMP_PINS[] = {38, 40, 42, 44, 46, 48, 50, 52};
static const uint8_t NUM_CHANNELS = 8;

// -- Default Activation Duration --
static const unsigned long DEFAULT_DURATION_MS = 5000UL;

// -- Per-Channel State Machine --
struct ChannelState
{
  bool active;            // currently running?
  uint8_t pin;            // output pin
  unsigned long startMs;  // millis() when activated
  unsigned long duration; // total duration in ms
};

static ChannelState channels[NUM_CHANNELS];

// -- Serial Command Buffer --
static const uint8_t CMD_BUF_SIZE = 32;
static char cmdBuf[CMD_BUF_SIZE];
static uint8_t cmdLen = 0;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Activate a channel for the given duration
static void activateChannel(uint8_t idx, unsigned long dur)
{
  if (idx >= NUM_CHANNELS)
    return;
  channels[idx].active = true;
  channels[idx].startMs = millis();
  channels[idx].duration = dur;
  digitalWrite(channels[idx].pin, HIGH);
  Serial.print(F("<ACK,"));
  Serial.print(idx);
  Serial.print(F(","));
  Serial.print(dur);
  Serial.println(F(">"));
}

// Stop a channel (pin LOW + confirm)
static void deactivateChannel(uint8_t idx)
{
  if (idx >= NUM_CHANNELS)
    return;
  channels[idx].active = false;
  digitalWrite(channels[idx].pin, LOW);
  Serial.print(F("<DONE,"));
  Serial.print(idx);
  Serial.println(F(">"));
}

// Parse and execute a command frame (content between < and >, inclusive)
static void processCommand(const char *buf)
{
  if (buf[0] != '<')
    return;

  const char *p = buf + 1;

  // -- Stop command: <S,index> --
  if (*p == 'S' || *p == 's')
  {
    const char *comma = strchr(p, ',');
    if (comma)
    {
      int idx = atoi(comma + 1);
      if (idx >= 0 && idx < NUM_CHANNELS)
      {
        deactivateChannel((uint8_t)idx);
      }
      else
      {
        Serial.println(F("<ERR,INVALID_INDEX>"));
      }
    }
    return;
  }

  // -- Activate command: <index> or <index,duration_ms> --
  int idx = atoi(p);
  unsigned long dur = DEFAULT_DURATION_MS;

  const char *comma = strchr(p, ',');
  if (comma)
  {
    dur = atol(comma + 1);
    // duration == 0 means stop, not "use default"
    if (dur == 0)
    {
      if (idx >= 0 && idx < NUM_CHANNELS)
      {
        deactivateChannel((uint8_t)idx);
      }
      return;
    }
  }

  if (idx < 0 || idx >= NUM_CHANNELS)
  {
    Serial.println(F("<ERR,INVALID_INDEX>"));
    return;
  }

  activateChannel((uint8_t)idx, dur);
}

// Non-blocking serial read: accumulate bytes, process on '>'
static void pollSerial()
{
  while (Serial.available())
  {
    char c = Serial.read();
    if (c == '<')
    {
      cmdLen = 0;
      cmdBuf[cmdLen++] = c;
    }
    else if (cmdLen > 0)
    {
      if (cmdLen < CMD_BUF_SIZE - 1)
      {
        cmdBuf[cmdLen++] = c;
      }
      if (c == '>')
      {
        cmdBuf[cmdLen] = '\0';
        processCommand(cmdBuf);
        cmdLen = 0;
      }
    }
  }
}

// Update all channels: deactivate those whose duration has elapsed
static void updateChannels()
{
  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_CHANNELS; i++)
  {
    if (channels[i].active)
    {
      if (now - channels[i].startMs >= channels[i].duration)
      {
        deactivateChannel(i);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Arduino Entry Points
// ---------------------------------------------------------------------------

void setup()
{
  Serial.begin(115200);

  for (uint8_t i = 0; i < NUM_CHANNELS; i++)
  {
    channels[i].pin = PUMP_PINS[i];
    channels[i].active = false;
    channels[i].startMs = 0;
    channels[i].duration = 0;
    pinMode(PUMP_PINS[i], OUTPUT);
    digitalWrite(PUMP_PINS[i], LOW);
  }

  Serial.println(F("<READY>"));
}

void loop()
{
  pollSerial();
  updateChannels();
}
