#!/usr/bin/env python3
"""
Scripts to drive a donkey 2 car and train a model for it. 

Usage:
    car.py (drive) [--model=<model>]
    car.py (train) (--tub=<tub>) (--model=<model>)
    car.py (calibrate) 
"""


import os
from docopt import docopt
import donkeycar as dk 

CAR_PATH = PACKAGE_PATH = os.path.dirname(os.path.realpath(__file__))
DATA_PATH = os.path.join(CAR_PATH, 'data')
MODELS_PATH = os.path.join(CAR_PATH, 'models')


def drive(model_path=None):
    #Initialized car
    V = dk.vehicle.Vehicle()
    cam = dk.parts.PiCamera()
    V.add(cam, outputs=['cam/image_array'], threaded=True)
    
    #modify max_throttle closer to 1.0 to have more power
    #modify steering_scale lower than 1.0 to have less responsive steering
    ctr = dk.parts.JoystickPilot(max_throttle=1.0, steering_scale=1.0)

    V.add(ctr, 
          inputs=['cam/image_array'],
          outputs=['user/angle', 'user/throttle', 'user/mode', 'recording'],
          threaded=True)
    
    #See if we should even run the pilot module. 
    #This is only needed because the part run_contion only accepts boolean
    def pilot_condition(mode):
        if mode == 'user':
            return False
        else:
            return True
        
    pilot_condition_part = dk.parts.Lambda(pilot_condition)
    V.add(pilot_condition_part, inputs=['user/mode'], outputs=['run_pilot'])
    
    #Run the pilot if the mode is not user.
    kl = dk.parts.KerasCategorical()
    if model_path:
        kl.load(model_path)
    
    V.add(kl, inputs=['cam/image_array'], 
          outputs=['pilot/angle', 'pilot/throttle'],
          run_condition='run_pilot')
    
    
    #Choose what inputs should change the car.
    def drive_mode(mode, 
                   user_angle, user_throttle,
                   pilot_angle, pilot_throttle):
        if mode == 'user' or model_path is None:
            return user_angle, user_throttle
        
        elif mode == 'local_angle':
            return pilot_angle, user_throttle
        
        else: 
            return pilot_angle, pilot_throttle
        
    drive_mode_part = dk.parts.Lambda(drive_mode)
    V.add(drive_mode_part, 
          inputs=['user/mode', 'user/angle', 'user/throttle',
                  'pilot/angle', 'pilot/throttle'], 
          outputs=['angle', 'target_throttle'])
    
    odometer = dk.parts.RotaryEncoder(mm_per_tick=0.1923, pin=23)
    V.add(odometer, outputs=['odometer/meters', 'odometer/meters_per_second'], threaded=True)

    def measured_throttle(current_velocity, current_throttle):
      max_velocity = 9.0
      if current_throttle < 0:
        direction = -1
      else:
        direction = 1

      return (current_velocity/max_velocity)*direction

    velocity_to_throttle_part = dk.parts.Lambda(measured_throttle)
    V.add(velocity_to_throttle_part,
          inputs=['odometer/meters_per_second', 'target_throttle'],
          outputs=['measured_throttle'])

    pid = dk.parts.PIDController()
    V.add(pid, 
          inputs=['target_throttle', 'measured_throttle'],
          outputs=['pid/output'])

    def throttle_with_pid(target_throttle, pid_output):
      return target_throttle + alpha

    pid_throttle_part = dk.parts.Lambda(throttle_with_pid)
    V.add(pid_throttle_part,
          inputs=['target_throttle','pid/output'],
          outputs=['pid_throttle'])

    steering_controller = dk.parts.PCA9685(1)
    steering = dk.parts.PWMSteering(controller=steering_controller,
                                    left_pulse=460, right_pulse=290)
    
    throttle_controller = dk.parts.PCA9685(0)
    throttle = dk.parts.PWMThrottle(controller=throttle_controller,
                                    max_pulse=500, zero_pulse=370, min_pulse=220)

    V.add(steering, inputs=['angle'])
    V.add(throttle, inputs=['pid_throttle'])
    
    #add tub to save data
    inputs=['cam/image_array',
            'user/angle', 'user/throttle', 
            #'pilot/angle', 'pilot/throttle', 
            'user/mode',
            'odometer/meters', 'odometer/meters_per_second',
            'target_throttle', 'measured_throttle', 'pid_throttle']
    types=['image_array',
           'float', 'float',  
           #'float', 'float', 
           'str', 
           'float', 'float', 
           'float', 'float', 'float']
    
    th = dk.parts.TubHandler(path=DATA_PATH)
    tub = th.new_tub_writer(inputs=inputs, types=types)
    V.add(tub, inputs=inputs, run_condition='recording')
    
    #run the vehicle for 20 seconds
    V.start(rate_hz=20)
    
    print("You can now go to <your pi ip address>:8887 to drive your car.")



def train(tub_name, model_name):
    
    kl = dk.parts.KerasCategorical()
    
    tub_path = os.path.join(DATA_PATH, tub_name)
    tub = dk.parts.Tub(tub_path)
    
    X_keys = ['cam/image_array']
    y_keys = ['user/angle', 'user/throttle']
    
    def rt(record):
        record['user/angle'] = dk.utils.linear_bin(record['user/angle'])
        return record
    
    train_gen, val_gen = tub.train_val_gen(X_keys, y_keys, 
                                           record_transform=rt, batch_size=128)
    
    model_path = os.path.join(MODELS_PATH, model_name)
    kl.train(train_gen, val_gen, saved_model_path=model_path)




def calibrate():
    channel = int(input('Enter the channel your actuator uses (0-15).'))
    c = dk.parts.PCA9685(channel)
    
    for i in range(10):
        pmw = int(input('Enter a PWM setting to test(100-600)'))
        c.run(pmw)


if __name__ == '__main__':
    args = docopt(__doc__)

    if args['drive']:
        drive(model_path = args['--model'])
    elif args['calibrate']:
        calibrate()
    elif args['train']:
        tub = args['--tub']
        model = args['--model']
        train(tub, model)




