import pytest

from app.safety_rules import assess_severity, choose_decision, classify_category


@pytest.mark.parametrize(
    "text, category",
    [
        ("My brakes are making a grinding noise", "brake"),
        ("Tire pressure light just came on", "tire"),
        ("Oil pressure is dropping fast", "engine"),
        ("The engine temperature is rising", "engine"),
        ("Battery light is flickering", "electrical"),
        ("Tell dispatch I am delayed", "communication"),
        ("Tell dispatch my brakes feel soft", "brake"),
        ("Just checking in", "general"),
    ],
)
def test_classify_category(text, category):
    assert classify_category(text) == category


@pytest.mark.parametrize(
    "text, severity",
    [
        ("My brakes are grinding", "critical"),
        ("There is smoke from the hood", "critical"),
        ("Oil pressure warning", "critical"),
        ("Check engine light is on", "warning"),
        ("Tire pressure light is on", "warning"),
        ("I'm running late", "low"),
        # whole-word matching: "fireworks" and "inflatable" must not trigger
        ("Saw fireworks over the highway", "low"),
    ],
)
def test_assess_severity(text, severity):
    assert assess_severity(text) == severity


def test_decisions():
    assert choose_decision("brake", "critical") == "STOP_SAFELY"
    assert choose_decision("tire", "warning") == "CONTINUE_WITH_CAUTION"
    assert choose_decision("communication", "low") == "SEND_MESSAGE"
    assert choose_decision("general", "low") == "LOG_ONLY"


@pytest.mark.parametrize(
    "text, severity",
    [
        # ruled out: reassuring absence or an explicit all-clear
        ("No smoke or anything, just the door squeaks", "low"),
        ("Not a fire, the alarm was a drill", "low"),
        ("Brakes are fine, it's just the radio", "low"),
        ("There's no fire but there is smoke from the hood", "critical"),
        # never ruled out: the absence itself is the hazard
        ("I have no brakes", "critical"),
        ("There's no steering response", "critical"),
        # an all-clear followed by "but" stays critical
        ("Brakes are fine but now there's grinding", "critical"),
        # downplaying is not ruling out
        ("A little smoke from the hood but I think it's fine", "critical"),
        # wheel and trailer hazards
        ("Front wheel is wobbling", "critical"),
        ("Trailer is swaying a lot", "critical"),
    ],
)
def test_negation_and_new_hazards(text, severity):
    assert assess_severity(text) == severity
