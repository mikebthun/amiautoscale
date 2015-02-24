#!/usr/bin/python -tt

import sys,getopt
 
import logging
import commands
import datetime
import json
import time


logger = logging.getLogger('stencil')
hdlr = logging.StreamHandler(sys.stdout)
#hdlr = logging.FileHandler('stencil.log') 
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr) 
logger.setLevel(logging.INFO) #logging.DEBUG


def help():

  print """ 

  Usage: ami-to-autoscale.py 



  --instance-id YOUR-INSTANCE-ID 
  --description "LIVE" 
  --autoscale-group LIVEWEB 
  --security-groups "sg-1 sg-2 sg-3" 
  [--max N (default 20)] 
  [--min N default 2] 
  [--instance-size m3.medium]
  [--help] 


  """
 
def main(argv):

  instance=None
  description=None
  securityGroups=None
  autoscaleGroup=None
  maxInstances=10
  minInstances=2
  instanceSize="t2.micro"

  #securityGroups="sg-0bdc126f sg-7abb751e"

  # make sure command line arguments are valid
  try:
    options, args = getopt.getopt(

       argv, 
      'hv', 
      [ 
        'help',
        'verbose',
        'instance-id=',
        'description=',
        'security-groups=',
        'autoscale-group=',
        'min=',
        'max=',
        'instance-size='
    
      ])
 
  except getopt.GetoptError:
    logging.fatal("Bad options!")
    help()
    sys.exit(2)


  # handle command line arugments
  for opt, arg in options:
    if opt in ('-h', '--help'):
      help()
      sys.exit(2)
    elif opt in ('-v', '--verbose'):
      logger.setLevel(logging.DEBUG) 
    elif opt in ('', '--description'):
      description=arg
    elif opt in ('', '--instance-id'):
      instance=arg
    elif opt in ('', '--security-groups'):
      securityGroups=arg
    elif opt in ('', '--autoscale-group'):
      autoscaleGroup=arg
    elif opt in ('', '--instance-size'):
      instanceSize=arg
    elif opt in ('', '--min'):
      minInstances=int(arg)
    elif opt in ('', '--max'):
     maxInstances=int(arg)

  if None in [instance,description,securityGroups,autoscaleGroup]:
     help()
     sys.exit(2)
 

  ###################################
  # main code starts here
  ###################################
  today = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")

  tag = "%s-%s" % ( description, today )
 
  # create the new AMI

  amiImageName = "%s-AMI" % ( tag )

  cmd = """aws ec2 create-image --name "%s" --instance-id %s --description "%s" """ % (
      
      amiImageName, 
      instance, 
      amiImageName

  	)


  logger.info("Create AMI %s" % amiImageName )

  (status,output) = commands.getstatusoutput(cmd)

  if status>0:
    logger.error("Could not create image: %s", cmd)
    logger.error(output)
    sys.exit(2)
 
  # grab the json

  try:
    j = json.loads(output)
    ami = j['ImageId']
  except:
  	logger.error("Could not parse ImageId from JSON")
  	sys.exit(2)

 
  # check status of AMI snapshot 
  # wait for snapshot to finish

  iteration = 0
  limit=25

  while True:

    iteration = iteration + 1

    if iteration > limit:
      logger.error("%s snapshot timeout" % ami)

    cmd = "aws ec2 describe-images --image-ids %s " %  ami

    logger.info("Checking %s" % ami)

    (status,output) = commands.getstatusoutput(cmd)

    try:
      j = json.loads(output)
      state = j['Images'][0]['State']
    except:
      logger.error("Could not parse state")
      sys.exit(2)

    if state == "available":
      break
    if state == "failed":
      logger.error("AMI Creation failed")
      sys.exit(2)
    else:
      logger.info(state)

    time.sleep(30)
 


  # create launch configuration


  launchConfigName = "%s-LAUNCH-CONFIG" % ( tag )
 
  cmd = """aws autoscaling create-launch-configuration --launch-configuration-name %s --image-id %s --instance-type %s --security-groups %s --instance-monitoring Enabled=true --associate-public-ip-address""" % (
  
    launchConfigName,
    ami,
    instanceSize,
    securityGroups

  )  


  (status,output) = commands.getstatusoutput(cmd)

  if status>0:
    logger.error("Could not create launch configuration: %s", cmd)
    logger.error(output)
    sys.exit(2)

 
  # wait for launch configuration to be available
  time.sleep(30)
  

  logger.info("Set new launch config to the autoscale group and bump max size")
 

  # # switch the scaling group to use this AMI
  # # double the size of the scaling group


  cmd = """aws autoscaling update-auto-scaling-group --auto-scaling-group-name "%s" --launch-configuration-name %s --min-size %d --max-size %d""" % (
   
     autoscaleGroup,
     launchConfigName,
     minInstances*2, # doubles amount of instances so we can clear old ones when we scale down
     maxInstances

  	)

  (status,output) = commands.getstatusoutput(cmd)

  if status>0:
    logger.error("Could not update auto scaling group: %s", cmd)
    logger.error(output)
    sys.exit(2)


  # lower it back to its normal size
  logger.info("Wait 7 minutes and then reduce size of autoscale group...")
 
  # sleep 7 minutes
  time.sleep(420)


  cmd = """aws autoscaling update-auto-scaling-group --auto-scaling-group-name "%s" --min-size %d --max-size %d""" % (
   
     autoscaleGroup,
     minInstances,
     maxInstances

  	)

  (status,output) = commands.getstatusoutput(cmd)

  if status>0:
    logger.error("Could not update auto scaling group: %s", cmd)
    logger.error(output)
    sys.exit(2)
 


  logger.info("Success")
  

if __name__ == "__main__":
  main(sys.argv[1:])