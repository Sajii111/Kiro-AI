"""The palm lock: recognising one person's palm from a photo (ICA 02).

A profile can be locked with a palm. Locking it takes a few photos of that palm (enrolment) and keeps an encrypted
template made from them, never the photos. Opening the profile takes one new photo, which is compared with the template
(verification). The answer is one of three outcomes: the palm matches (Authentication Successful), it does not
(Authentication Failed), or the photo cannot be judged (Invalid Image).

How a photo becomes a template:

1. `roi`      the hand is straightened with the palm's own frame and a square in the middle of the palm is cut out
2. `prep`     the square is turned into an even, normalised grey picture
3. `crease`   method A: where the palm's creases run (a valley filter), compared as maps and as direction histograms
   `compcode` method B: the strongest line direction in every small block (a bank of Gabor filters, "competitive code")
   `lbp`      a spare texture method, reported for comparison but not used for the decision
4. `match`    each method's similarity is normalised with numbers measured on validation photos, then the two are
              averaged into one score that is compared with one threshold (`calibration.json`)
5. `template` the features of the enrolment photos, sealed with a key (Fernet) before they are stored

`engine` ties the steps together: `extract`, `enrol` and `verify`.
"""
