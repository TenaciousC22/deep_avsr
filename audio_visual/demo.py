"""
Author: Smeet Shah
Copyright (c) 2020 Smeet Shah
File part of 'deep_avsr' GitHub repository available at -
https://github.com/lordmartian/deep_avsr

Specifications:
--------------
Videofile - .mp4 file
Properties - Video:
             25 fps, 160x160 RGB frames, Mouth approx. in center,
             face size should be comparable to frame size
             Audio:
             Mono audio, 16000 Hz sample rate

Note -
Video length should be such that the expected transcription length is less than 100 characters.
For this, a long video can be appropriately segmented into clips of appropriate length
depending on the speaking rate of the speaker. For a speaker with around 160 words per min,
and considering 6 characters per word (including space) on average, clip lengths should be
around 6 secs.
The predicted transcriptions will have all characters in capital with no punctuations
other than an apostrophe (').
"""

import torch
import numpy as np
import os
import csv

from config import args
from models.av_net import AVNet
from models.lrs2_char_lm import LRS2CharLM
from models.visual_frontend import VisualFrontend
from data.utils import prepare_main_input, collate_fn
from utils.preprocessing import preprocess_sample
from utils.decoders import ctc_greedy_decode, ctc_search_decode



def main():

    np.random.seed(args["SEED"])
    torch.manual_seed(args["SEED"])
    gpuAvailable = torch.cuda.is_available()
    device = torch.device("cuda" if gpuAvailable else "cpu")


    if args["TRAINED_MODEL_FILE"] is not None:

        print("\nTrained Model File: %s" %(args["TRAINED_MODEL_FILE"]))
        print("\nDemo Directory: %s" %(args["DEMO_DIRECTORY"]))


        #declaring the model and loading the trained weights
        model = AVNet(args["TX_NUM_FEATURES"], args["TX_ATTENTION_HEADS"], args["TX_NUM_LAYERS"], args["PE_MAX_LENGTH"],
                      args["AUDIO_FEATURE_SIZE"], args["TX_FEEDFORWARD_DIM"], args["TX_DROPOUT"], args["NUM_CLASSES"])
        model.load_state_dict(torch.load(args["CODE_DIRECTORY"] + args["TRAINED_MODEL_FILE"], map_location=device))
        model.to(device)


        #declaring the visual frontend module
        vf = VisualFrontend()
        vf.load_state_dict(torch.load(args["TRAINED_FRONTEND_FILE"], map_location=device))
        vf.to(device)


        #declaring the language model
        lm = LRS2CharLM()
        lm.load_state_dict(torch.load(args["TRAINED_LM_FILE"], map_location=device))
        lm.to(device)
        if not args["USE_LM"]:
            lm = None


        #reading the noise file
        if args["TEST_DEMO_NOISY"]:
            _, noise = wavfile.read(args["DATA_DIRECTORY"] + "/noise.wav")
        else:
            noise = None


        print("\n\nRunning Demo .... \n")

        rows=[]

        print(args['TEST_DEMO_MODE'])

        #walking through the demo directory and running the model on all video files in it
        for root, dirs, files in os.walk(args["DEMO_DIRECTORY"]):
            for file in files:
                if file.endswith(".mp4"):

                    sNum=file[7]

                    if file[13]<="9" and file[13]>="0":
                        cNum=file[12:14]
                    else:
                        cNum=file[12]

                    if file[-6]=="l":
                        cType="jumble"
                    elif file[-6]=="s":
                        cType="base"
                    else:
                        cType=file[-8:-4]


                    sampleFile = os.path.join(root, file[:-4])

                    #preprocessing the sample
                    params = {"roiSize":args["ROI_SIZE"], "normMean":args["NORMALIZATION_MEAN"], "normStd":args["NORMALIZATION_STD"], "vf":vf}
                    preprocess_sample(sampleFile, params)

                    #converting the data sample into appropriate tensors for input to the model
                    audioFile = os.path.join(root, file[:-4]) + ".wav"
                    visualFeaturesFile = os.path.join(root, file[:-4]) + ".npy"
                    audioParams = {"stftWindow":args["STFT_WINDOW"], "stftWinLen":args["STFT_WIN_LENGTH"], "stftOverlap":args["STFT_OVERLAP"]}
                    videoParams = {"videoFPS":args["VIDEO_FPS"]}
                    inp, _, inpLen, _ = prepare_main_input(audioFile, visualFeaturesFile, None, noise, args["MAIN_REQ_INPUT_LENGTH"],
                                                           args["CHAR_TO_INDEX"], args["NOISE_SNR_DB"], audioParams, videoParams)
                    inputBatch, _, inputLenBatch, _ = collate_fn([(inp, None, inpLen, None)])

                    #running the model
                    inputBatch = ((inputBatch[0].float()).to(device), (inputBatch[1].float()).to(device))
                    inputLenBatch = (inputLenBatch.int()).to(device)
                    if args["TEST_DEMO_MODE"] == "AO":
                        inputBatch = (inputBatch[0], None)
                    elif args["TEST_DEMO_MODE"] == "VO":
                        inputBatch = (None, inputBatch[1])
                    elif args["TEST_DEMO_MODE"] == "AV":
                        pass
                    else:
                        print("Invalid Operation Mode.")
                        exit()

                    model.eval()
                    with torch.no_grad():
                        outputBatch = model(inputBatch)

                    #obtaining the prediction using CTC deocder
                    if args["TEST_DEMO_DECODING"] == "greedy":
                        predictionBatch, predictionLenBatch = ctc_greedy_decode(outputBatch, inputLenBatch, args["CHAR_TO_INDEX"]["<EOS>"])

                    elif args["TEST_DEMO_DECODING"] == "search":
                        beamSearchParams = {"beamWidth":args["BEAM_WIDTH"], "alpha":args["LM_WEIGHT_ALPHA"], "beta":args["LENGTH_PENALTY_BETA"],
                                            "threshProb":args["THRESH_PROBABILITY"]}
                        predictionBatch, predictionLenBatch = ctc_search_decode(outputBatch, inputLenBatch, beamSearchParams,
                                                                                args["CHAR_TO_INDEX"][" "], args["CHAR_TO_INDEX"]["<EOS>"], lm)
                    else:
                        print("Invalid Decode Scheme")
                        exit()

                    #converting character indices back to characters
                    pred = predictionBatch[:][:-1]
                    pred = "".join([args["INDEX_TO_CHAR"][ix] for ix in pred.tolist()])

                    #printing the predictions
                    print("File: %s" %(file))
                    print("Speaker: "+sNum+"   Clip: "+cNum+"   Clip Type: "+cType)
                    print("Prediction: %s" %(pred))
                    print("\n")
                    row=[sNum,cNum,cType,pred]
                    rows.append(row)


        print("Demo Completed.\n")
        with open("predictions-noise-10db.csv","w",newline="") as file:
            writer=csv.writer(file)
            for x in range(len(rows)):
                writer.writerow(rows[x])

    else:
        print("\nPath to trained model file not specified.\n")

    return



if __name__ == "__main__":
    main()
