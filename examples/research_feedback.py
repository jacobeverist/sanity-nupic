import random
from collections import deque

from nupic.data.generators.pattern_machine import PatternMachine
from nupic.data.generators.sequence_machine import SequenceMachine
from htmresearch.algorithms.extended_temporal_memory import ExtendedTemporalMemory
from htmresearch.support.etm_monitor_mixin import ExtendedTemporalMemoryMonitorMixin

from htmsanity.nupic.runner import SanityRunner
from htmsanity.nupic.model import SanityModel, segmentsFromConnections

class MonitoredExtendedTemporalMemory(ExtendedTemporalMemoryMonitorMixin,
                                      ExtendedTemporalMemory):
    pass

DEFAULT_TEMPORAL_MEMORY_PARAMS = {
    "columnDimensions": (2048,),
    "cellsPerColumn": 20,
    "activationThreshold": 20,
    "initialPermanence": 0.5,
    "connectedPermanence": 0.6,
    "minThreshold": 20,
    "maxNewSynapseCount": 40,
    "permanenceIncrement": 0.10,
    "permanenceDecrement": 0.02,
    "predictedSegmentDecrement": 0.08,
    "seed": 42,
    "apicalInputDimensions": (2048,),
    "learnOnOneCell": False}

def generateSequences(patternDimensionality, patternCardinality, sequenceLength,
                      sequenceCount):
    patternAlphabetSize = sequenceLength * sequenceCount
    patternMachine = PatternMachine(patternDimensionality, patternCardinality,
                                    patternAlphabetSize)
    sequenceMachine = SequenceMachine(patternMachine)
    numbers = sequenceMachine.generateNumbers(sequenceCount, sequenceLength)
    generatedSequences = sequenceMachine.generateFromNumbers(numbers)

    return [sorted(s) if s is not None else None
            for s in generatedSequences]

def serializePattern(patternSet):
    return ','.join(sorted([str(x) for x in patternSet]))

def getAlphabet(sequences):
    alphabetOfPatterns = []
    count = 0
    alphabet = {}

    for sensorPattern in sequences:
        if sensorPattern is not None:
            ser = serializePattern(sensorPattern)
            if ser not in alphabet:
                alphabet[ser] = chr(count + ord('A'))
                count += 1

    return alphabet

def labelPattern(pattern, alphabet):
    if pattern is None:
        return None
    ser = serializePattern(pattern)
    if ser in alphabet:
        return alphabet[ser]
    return '?'

def shiftingFeedback(starting_feedback, n, percent_shift=0.2):

    feedback_seq = []
    feedback = starting_feedback

    for _ in range(n):
        feedback = set([x for x in feedback])
        p = int(percent_shift*len(feedback))
        toRemove = set(random.sample(feedback, p))
        toAdd = set([random.randint(0, 2047) for _ in range(p)])
        feedback = (feedback - toRemove) | toAdd
        feedback_seq.append(sorted(feedback))

    return feedback_seq

def confusionMatrixStats(tm, timestep):
    predAct = len(tm.mmGetTracePredictedActiveCells().data[timestep])
    predInact = len(tm.mmGetTracePredictedInactiveCells().data[timestep])
    unpredAct = len(tm.mmGetTraceUnpredictedActiveColumns().data[timestep])

    pred_or_act = tm.mmGetTraceUnpredictedActiveColumns().data[timestep] | (
        tm.mmGetTracePredictedActiveColumns().data[timestep] | (
            tm.mmGetTracePredictedInactiveColumns().data[timestep]))

    unpredInact = tm.numberOfColumns()-len(pred_or_act)

    return predAct, unpredAct, predInact, unpredInact

def printConfusionMatrix(mat):
    print "\t predicted neurons \t unpredicted columns"
    print "active: \t ", mat[0], '\t\t\t', mat[1]
    print "inactive: \t ", mat[2], '\t\t\t', mat[3]


class FeedbackExperimentSanityModel(SanityModel):
    def __init__(self, tm, nTrainTrials, trainSeq, trainFeedbackSeq,
                 testSeq, testFeedbackSeq, feedbackBuffer, nFeedbackActive,
                 alphabet):
        super(FeedbackExperimentSanityModel, self).__init__()
        self.tm = tm
        self.nTrainTrials = nTrainTrials
        self.trainSeq = trainSeq
        self.trainFeedbackSeq = trainFeedbackSeq
        self.testSeq = testSeq
        self.testFeedbackSeq = testFeedbackSeq
        self.feedbackBuffer = feedbackBuffer
        self.nFeedbackActive = nFeedbackActive
        self.alphabet = alphabet
        self.didFinalOutput = False

        self.lastInputIndex = -1

    def step(self):
        self.lastInputIndex += 1

        trialDuration = len(self.trainSeq)
        trainDuration = trialDuration * self.nTrainTrials

        if self.lastInputIndex < trainDuration:
            trial = self.lastInputIndex / trialDuration
            i = self.lastInputIndex % trialDuration
            pattern = self.trainSeq[i]
            if pattern is None:
                self.tm.reset()
            else:
                feedback = None
                if trial < self.feedbackBuffer:
                    feedback = sorted(set([random.randint(0, 2047)
                                           for _ in range(self.nFeedbackActive)]))
                else:
                    feedback = self.trainFeedbackSeq[i]

                self.tm.compute(pattern, activeCellsExternalApical=feedback,
                                reinforceCandidatesExternalApical=feedback,
                                growthCandidatesExternalApical=feedback,
                                learn=True)
        elif self.lastInputIndex < trainDuration + len(self.testSeq):
            i = self.lastInputIndex - trainDuration

            if i == 0:
                self.tm.reset()

            pattern = self.testSeq[i]
            feedback = self.testFeedbackSeq[i]
            if pattern is None:
                self.tm.reset()
            else:
                self.tm.compute(pattern, activeApicalCells=feedback,
                                learn=True, sequenceLabel=None)
        else:
            self.lastInputIndex -= 1 # undo
            if not self.didFinalOutput:
                timestep = len(self.testSeq) - 2
                print "Considering timestep " + str(timestep)
                print "Feedback confusion matrix: "
                printConfusionMatrix(confusionMatrixStats(self.tm, timestep))
                print
                self.didFinalOutput = True
            return False

    def getInputDisplayText(self):

        trialDuration = len(self.trainSeq)
        trainDuration = trialDuration * self.nTrainTrials

        stage = None
        pattern = None

        if self.lastInputIndex < trainDuration:
            trial = self.lastInputIndex / trialDuration
            i = self.lastInputIndex % trialDuration
            stage = "Train (trial %d of %d)" % (trial + 1, self.nTrainTrials)
            pattern = self.trainSeq[i]
        elif self.lastInputIndex < trainDuration + len(self.testSeq):
            i = self.lastInputIndex - trainDuration
            stage = "Test"
            pattern = self.testSeq[i]
        else:
            assert False

        if self.lastInputIndex >= 0:
            return [
                ('stage', stage),
                ('input', labelPattern(pattern, self.alphabet)),
            ]
        else:
            return []

    def query(self, bitHistory, getNetworkLayout=False, getBitStates=False,
              getProximalSegments=False, proximalSegmentsQuery={},
              getDistalSegments=False, distalSegmentsQuery={},
              getApicalSegments=False, apicalSegmentsQuery={}):
        senses = {
        }
        layers = {
            'tm': {},
            'pseudo': {},
        }

        tm = self.tm

        if getNetworkLayout:
            layers['tm'].update({
                'cellsPerColumn': tm.cellsPerColumn,
                'dimensions': tm.columnDimensions,
                'ordinal': 0,
            })

            layers['pseudo'].update({
                'cellsPerColumn': 1,
                'dimensions': [2048],
                'ordinal': 1,
            })

        if getBitStates:
            pattern = None
            feedbackPattern = None
            if self.lastInputIndex >= 0:
                trialDuration = len(self.trainSeq)
                trainDuration = trialDuration * self.nTrainTrials

                if self.lastInputIndex < trainDuration:
                    i = self.lastInputIndex % trialDuration
                    pattern = self.trainSeq[i]
                    feedbackPattern = set(self.trainFeedbackSeq[i])
                elif self.lastInputIndex < trainDuration + len(self.testSeq):
                    i = self.lastInputIndex - trainDuration
                    pattern = self.testSeq[i]
                    feedbackPattern = set(self.testFeedbackSeq[i])
                else:
                    assert False

            activeBits = set()
            if pattern is not None:
                activeBits = set(pattern)

            predictiveCells = set(tm.getPredictiveCells())
            predictiveColumns = set(cell / tm.cellsPerColumn for cell in predictiveCells)
            layers['tm'].update({
                'activeColumns': activeBits,
                'activeCells': set(tm.activeCells),
                'predictiveCells': set(predictiveCells),
                'predictiveColumns': predictiveColumns,
            })

            activeFeedbackColumns = set()
            if feedbackPattern is not None:
                activeFeedbackColumns = set(feedbackPattern)

            layers['pseudo'].update({
                'activeColumns': feedbackPattern,
                'activeCells': feedbackPattern,
                'predictiveCells': set(),
                'predictiveColumns': set(),
            })

        if getDistalSegments or getApicalSegments:
            assert getBitStates
            try:
                prevState = bitHistory.next()
                columnsToCheck = (layers['tm']['activeColumns'] |
                                  prevState['layers']['tm']['predictiveColumns'])

                if getDistalSegments:
                    onlySources = prevState['layers']['tm']['activeCells']
                    sourcePath = ('layers', 'tm')
                    onlyActiveSynapses = distalSegmentsQuery['onlyActiveSynapses']
                    onlyConnectedSynapses = distalSegmentsQuery['onlyConnectedSynapses']
                    distalSegments = segmentsFromConnections(tm.basalConnections, tm,
                                                             columnsToCheck, onlySources,
                                                             sourcePath,
                                                             onlyActiveSynapses,
                                                             onlyConnectedSynapses)
                    layers['tm'].update({
                        'distalSegments': distalSegments,
                        "nDistalLearningThreshold": tm.minThreshold,
                        "nDistalStimulusThreshold": tm.activationThreshold,
                    })
                if getApicalSegments:
                    onlySources = prevState['layers']['pseudo']['activeCells']
                    sourcePath = ('layers', 'pseudo')
                    sourceCellsPerColumn = 1
                    sourceCellOffset = -tm.numberOfCells()
                    onlyActiveSynapses = apicalSegmentsQuery['onlyActiveSynapses']
                    onlyConnectedSynapses = apicalSegmentsQuery['onlyConnectedSynapses']
                    apicalSegments = segmentsFromConnections(tm.apicalConnections, tm,
                                                             columnsToCheck, onlySources,
                                                             sourcePath,
                                                             onlyActiveSynapses,
                                                             onlyConnectedSynapses,
                                                             sourceCellOffset)
                    layers['tm'].update({
                        'apicalSegments': apicalSegments,
                        "nApicalLearningThreshold": tm.minThreshold,
                        "nApicalStimulusThreshold": tm.activationThreshold,
                    })
            except StopIteration:
                # No previous timestep available.
                pass

        return {
            'senses': senses,
            'layers': layers,
        }

def experiment2():
    """
    Disambiguation experiment.
    Experiment setup:
      Train TM on sequences ABCDE and XBCDF with feedback
      Test TM on partial ambiguous sequences BCDE and BCDF
        With correct feedback

    Desired result:
      With correct feedback, TM should make correct prediction after D
    """
    print "Initializing temporal memory..."
    params = dict(DEFAULT_TEMPORAL_MEMORY_PARAMS)
    tmFeedback = MonitoredExtendedTemporalMemory(mmName="TM2", **params)
    feedback_n = 400
    trials = 30
    print "Done."

    # Create two sequences with format "ABCDE" and "XBCDF"
    sequences1 = generateSequences(2048, 40, 5, 1)

    sequences2 = list(sequences1)
    sequences2[0] = sorted(set(random.randint(0, 2047) for _ in sequences1[0]))
    sequences2[-2] = sorted(set(random.randint(0, 2047) for _ in sequences1[-2]))

    fixed_feedback1 = sorted(set([random.randint(0, 2047) for _ in range(feedback_n)]))
    fixed_feedback2 = sorted(set([random.randint(0, 2047) for _ in range(feedback_n)]))
    feedback_seq1 = shiftingFeedback(fixed_feedback1, len(sequences1))
    feedback_seq2 = shiftingFeedback(fixed_feedback2, len(sequences2))

    sequences = sequences1 + sequences2
    feedback_seq = feedback_seq1 + feedback_seq2
    alphabet = getAlphabet(sequences)
    partial_sequences1 = sequences1[1:]
    partial_sequences2 = sequences2[1:]

    print "train TM on sequences ABCDE and XBCDF"
    test_sequence = partial_sequences1
    print "test TM on sequence BCDE, evaluate responses to E"

    testFeedback = feedback_seq1
    print 'Feedback is in "ABCDE" state'
    print 'Desired outcome: '
    print '\t no extra prediction with feedback (~0 predicted inactive cell)'
    print

    feedbackBuffer = 10
    sanityModel = FeedbackExperimentSanityModel(tmFeedback, trials, sequences,
                                                feedback_seq, test_sequence, testFeedback,
                                                feedbackBuffer, feedback_n, alphabet)
    runner = SanityRunner(sanityModel)
    runner.start()

if __name__ == "__main__":
    experiment2()
