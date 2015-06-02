#!/usr/bin/python -tt

import sys,getopt
 
import logging
import commands
import datetime
import json
import time
import re

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
  [--keyname]
  [--max N (default 20)] 
  [--min N default 2] 
  [--instance-size m3.medium]
  [--help] 


  """


def Run(cmd):
 
  print "** Running:", cmd,

  (status,output) = commands.getstatusoutput(cmd)

  if status > 0:
    logger.error(output)
    sys.exit(2)

  print '[OK]'
  return output


def getInstances(autoscaleGroup):
  cmd = "aws autoscaling describe-auto-scaling-groups --auto-scaling-group-name %s" % autoscaleGroup
  output = Run(cmd)

  scaling_group_details = json.loads(output)
 
  try:
    instances = scaling_group_details['AutoScalingGroups'][0]['Instances']
  except:
    logger.error("FATAL: Could not get current instances count from auto scale group %s", )

  return instances



def main(argv):

  instance=None
  description=None
  securityGroups=None
  autoscaleGroup=None
  maxInstances=10
  minInstances=2
  instanceSize="t2.micro"
  keyname=""
  daysToKeep=7


  # make sure command line arguments are valid
  try:
    options, args = getopt.getopt(

       argv, 
      'hvi:d:a:s:', 
      [ 
        'help',
        'verbose',
        'instance-id=',
        'description=',
        'security-groups=',
        'autoscale-group=',
        'min=',
        'max=',
        'instance-size=',
        'keyname='
    
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
    elif opt in ('-d', '--description'):
      description=arg
    elif opt in ('-i', '--instance-id'):
      instance=arg
    elif opt in ('-s', '--security-groups'):
      securityGroups=arg
    elif opt in ('-a', '--autoscale-group'):
      autoscaleGroup=arg
    elif opt in ('', '--instance-size'):
      instanceSize=arg
    elif opt in ('', '--min'):
      minInstances=int(arg)
    elif opt in ('', '--max'):
     maxInstances=int(arg)
    elif opt in ('', '--keyname'):
     keyname="--key-name %s" % arg

  if None in [instance,description,securityGroups,autoscaleGroup]:
     help()
     sys.exit(2)
 

  ###################################
  # main code starts here
  ###################################
  
  # get current number of instances so we can double
  instances = getInstances(autoscaleGroup)
 
  currentInstanceCount = len(instances)

  if currentInstanceCount < 1:
    currentInstanceCount = 1

  today = datetime.datetime.now().strftime("%Y-%m-%d-%s") 
  
  tag = "%s-%s" % ( description, today )
 
  # create the new AMI

  amiImageName = "%s-AMI" % ( tag )

  cmd = """aws ec2 create-image --name "%s" --instance-id %s --description "%s" """ % (
      
      amiImageName, 
      instance, 
      amiImageName

  	)

  logger.info("Create AMI %s" % amiImageName )
  output = Run(cmd) #print output
 
  # grab the json

  try:
    j = json.loads(output)
    ami = j['ImageId']
  except:
    logger.error("FATAL: Could not parse ImageId from JSON")
    logger.error("CMD: %s" % cmd)
    logger.error("JSON: %s" % j)
    sys.exit(2)

 
  ## tag the AMI
  amitag = "ami-to-autoscale-%s" % description
  cmd = """aws ec2 create-tags --resources %s --tags Key=%s,Value=%f""" % ( ami, amitag, time.time() )
  output = Run(cmd)

  print output


  cmd = """aws ec2 describe-images --filters Name=tag-key,Values=%s""" % amitag
  output = Run(cmd)

  try:
    j = json.loads(output)
    rawImages = j['Images']
  except:
    logger.error("FATAL: Could not parse ImageId from JSON")
    logger.error("CMD: %s" % cmd)
    logger.error("JSON: %s" % j)
    sys.exit(2)
 

 
  # check status of AMI snapshot 
  # wait for snapshot to finish

  iteration = 0
  limit=30 # 15 minutes 30 @ 30 sec intervals

  while True:

    iteration = iteration + 1

    if iteration > limit:
      logger.error("%s snapshot timeout" % ami)

    cmd = "aws ec2 describe-images --image-ids %s " %  ami

    logger.info("Checking %s" % ami)

    output = Run(cmd)

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
      logger.error("OUTPUT: %s" % output)
      sys.exit(2)
    else:
      logger.info(state)

    time.sleep(30)
 

  # Remove old AMIs here
  expiredTime = time.time() - ((60*60)*24)*daysToKeep # seven days of AMIs  
 
  # only run if we have enough images to delete
  if len(rawImages) > 3:
    for image in rawImages:
      try:
        for tg in image['Tags']:
          if tg['Key'] == amitag:
            if float(tg['Value']) < expiredTime:
              logger.info("EXPIRED - Deleting: %s %s " % ( image['ImageId'], tg['Value'] ))
              cmd = "aws ec2 deregister-image --image-id %s" % image['ImageId']

              output = Run(cmd)
              
              ## delete the launch config attached to this AMI if it exists
              try:
                m = re.match(r'(.*)-AMI$', image['Name'])
                if m:
                  cmd = "aws autoscaling delete-launch-configuration --launch-configuration-name %s-LAUNCH-CONFIG" % m.group(1)
                  output = Run(cmd)
                  logger.info(output)
              except:
                pass
         
  
      except Exception, e:
        print "Fatal", e
        sys.exit(2)

  # create launch configuration
  launchConfigName = "%s-LAUNCH-CONFIG" % ( tag )

  logger.info("Creating new launch config and wait 30 seconds...")
 
  cmd = """aws autoscaling create-launch-configuration --launch-configuration-name %s --image-id %s --instance-type %s --security-groups %s --instance-monitoring Enabled=true --associate-public-ip-address %s""" % (
  
    launchConfigName,
    ami,
    instanceSize,
    securityGroups,
    keyname

  )  

 
  Run(cmd)
 
  # remove old launch configs here


  # wait for launch configuration to be available
  time.sleep(30)
  

  logger.info("Update autoscale group and bump max size")
 
  ## switch the scaling group to use this AMI
  ## double the size of the scaling group
  cmd = """aws autoscaling update-auto-scaling-group --auto-scaling-group-name "%s" --launch-configuration-name %s --min-size %d --max-size %d""" % (
   
     autoscaleGroup,
     launchConfigName,
     currentInstanceCount*2, # doubles amount of instances so we can clear old ones when we scale down
     (currentInstanceCount*2)*2 # bump high during transition

  	)

  Run(cmd)

  # loop over all instances waiting for them to be available before descaling
  logger.info("Wait for new scaleup instances to intialize...")
 
  # loop over all instances and check status
 
  timeout = 760
  start = time.time()
  waitingForNewInstances=True

  while True:
    
    runningTime = time.time()-start
    logger.info("Checking new instances status (Elapsed %.3f)" % runningTime)

    # dont spam
    time.sleep(15)

    checkInstances = getInstances(autoscaleGroup)

    if currentInstanceCount == len(checkInstances) and waitingForNewInstances:
      waitingForNewInstances=None
      logger.info("No new instances yet... (Elapsed %.3f Original Instance Count: %d  Current Instance Count: %d)" %  ( runningTime, currentInstanceCount, len(checkInstances)) )
      continue 
    
    healthy=True

    for instance in checkInstances:
  
      if instance['LifecycleState'] != 'InService':
        logger.info("Instance not in service yet: %s", instance['InstanceId'] )
        healthy = False
  
      if instance['HealthStatus'] != 'Healthy':
        logger.info("Instance not healthy yet: %s", instance['InstanceId'] )
        healthy=False
  
    # all instances are good -- lets break
    if healthy:
      break

    # we have timed out
    if runningTime > timeout:
      logger.error("FATAL: Instances scale up timed out on health check")
      sys.exit(2)



  # handle desired
  desiredCapacity = currentInstanceCount
  
  # make sure we have at least two instances
  if desiredCapacity < 2:
    desiredCapacity=2

  # make sure desired is not greater than max
  if desiredCapacity > maxInstances:
    desiredCapacity=maxInstances

  # descale and set to desired counts (normal size)
  logger.info("Descale and set to desired counts")
  cmd = """aws autoscaling update-auto-scaling-group --auto-scaling-group-name "%s" --min-size %d --max-size %d --desired-capacity %d""" % (
   
     autoscaleGroup,
     minInstances,
     maxInstances,
     desiredCapacity
  	)

  Run(cmd)
 
  logger.info("Success")
  

if __name__ == "__main__":
  main(sys.argv[1:])
