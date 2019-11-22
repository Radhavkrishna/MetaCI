#!/bin/bash

python /app/manage.py migrate
if [ "${BUILD_ENV}" = "development" ] ; then
    echo "POPULATING DATABASE WITH TEST DATA..."
    python /app/manage.py populate_db;
    python /app/manage.py metaci_scheduled_jobs;
    echo "CREATING ADMIN USER FOR TESTING PURPOSES..."
    echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@salesforce.com', 'password')" | python manage.py shell
fi
echo $SFDX_HUB_USERNAME
echo $SFDX_HUB_KEY > /app/sfdx_hub.key
echo $(cat /app/sfdx_hub.key)
sfdx force:auth:jwt:grant -u $SFDX_HUB_USERNAME -f /app/sfdx_hub.key -i $SFDX_CLIENT_ID --setdefaultdevhubusername
yarn serve
echo "ALL DONE!"