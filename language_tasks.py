"""Local task wording; content and speech accuracy still require language review."""
import re


def local_tasks(passage, mentor_goal, buddy_goal, language):
    words = list(dict.fromkeys(re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*", passage.casefold())))
    vocabulary = sorted(words, key=lambda word: -len(word))[:3]
    focus = ', '.join(vocabulary)
    if language == 'fil':
        mentor = {
            'Explain word meanings': f'Ipaliwanag sa sariling salita ang kahulugan ng: {focus}. Gamitin ang isa sa bagong pangungusap.',
            'Use context clues': f'Hanapin sa teksto ang: {focus}. Ipakita ang mga salitang nakatutulong upang maunawaan ang kahulugan.',
            'Teach vocabulary clearly': f'Ituro sa iyong kapareha ang: {focus}. Magbigay ng paliwanag at halimbawa, at ipapaliwanag muli ang isa.',
        }
        buddy = {
            'Find key details': 'Magbigay ng dalawang mahalagang detalye. Ituro ang mga salita sa teksto na sumusuporta sa iyong sagot.',
            'Retell in sequence': 'Ikuwento o ipaliwanag ang binasa sa tamang pagkakasunod: una, sumunod, at huli. Gumamit ng mga detalye mula sa teksto.',
            'Make supported inferences': 'Anong ideya ang mahihinuha kahit hindi direktang sinabi? Ituro ang pahiwatig sa teksto at ipaliwanag ang sagot.',
        }
        teach_back = 'Buddy: ituro muli sa mentor ang isang bagong salita o ideya mula sa binasa. Mentor: makinig at magtanong upang linawin ang paliwanag.'
    else:
        mentor = {
            'Explain word meanings': f'Ipasabot sa kaugalingong mga pulong ang kahulogan sa: {focus}. Gamita ang usa sa bag-ong hugpong sa mga pulong.',
            'Use context clues': f'Pangitaa sa teksto ang: {focus}. Ipakita ang mga pulong nga makatabang sa pagsabot sa kahulogan.',
            'Teach vocabulary clearly': f'Itudlo sa imong kauban ang: {focus}. Paghatag og pasabot ug pananglitan, dayon ipasabot pag-usab ang usa.',
        }
        buddy = {
            'Find key details': 'Paghatag og duha ka importanteng detalye. Itudlo ang mga pulong sa teksto nga nagsuporta sa imong tubag.',
            'Retell in sequence': 'Isugilon o ipasabot ang gibasa sa hustong han-ay: una, sunod, ug kataposan. Gamita ang mga detalye gikan sa teksto.',
            'Make supported inferences': 'Unsang ideya ang imong masabtan bisan wala kini direktang gisulti? Itudlo ang timailhan sa teksto ug ipasabot ang tubag.',
        }
        teach_back = 'Buddy: itudlo pag-usab sa mentor ang usa ka bag-ong pulong o ideya gikan sa gibasa. Mentor: paminaw ug pangutana aron maklaro ang pasabot.'
    return dict(mentor=mentor[mentor_goal], buddy=buddy[buddy_goal], vocabulary=vocabulary, teach_back=teach_back)
